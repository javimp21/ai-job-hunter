"""Company Hunter orchestration: company context, contact choice and saved drafts.

Drafts are stored as ordinary ``Outreach`` rows (purpose COLD_OUTREACH, status
DRAFT) so the existing lifecycle applies; nothing here can send anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_job_hunter.candidates.technologies import extract_job_technologies
from ai_job_hunter.company_hunter.ranking import (
    CompanyFit,
    CompanyStage,
    _board_job_counts,
    company_inputs,
    score_company,
)
from ai_job_hunter.company_hunter.relevance import relevance
from ai_job_hunter.company_hunter.writing import (
    DEFAULT_CV_DIR,
    CompanyFacts,
    HunterWritingError,
    PersonFacts,
    generate_company_drafts,
    load_base_cv,
    load_style_guide,
    resolve_language,
)
from ai_job_hunter.models import (
    Company,
    CompanyLead,
    Contact,
    Job,
    Outreach,
    OutreachChannel,
    OutreachPurpose,
    OutreachStatus,
)
from ai_job_hunter.services.cover_letters import DEFAULT_STYLE_GUIDE_PATH, MessagesClient
from ai_job_hunter.services.outreach_persistence import (
    InvalidOutreachTransition,
    create_outreach,
    find_active_duplicate,
    transition_outreach,
)

@dataclass(frozen=True, slots=True)
class CompanyContext:
    company: Company
    fit: CompanyFit
    facts: CompanyFacts
    contacts: tuple[Contact, ...]


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    company: Company
    stage: CompanyStage
    language: str
    contact: Contact | None
    email: Outreach
    linkedin: Outreach
    created: bool  # False when active drafts already existed and were returned (no model call)


def load_company(session: Session, company_id: UUID) -> Company | None:
    return session.scalar(
        select(Company)
        .options(selectinload(Company.evidence_items), selectinload(Company.jobs).selectinload(Job.sources))
        .where(Company.id == company_id)
    )


def company_context(session: Session, company_id: UUID) -> CompanyContext:
    company = load_company(session, company_id)
    if company is None:
        raise HunterWritingError(f"Unknown company id: {company_id}.")
    leads = session.scalars(select(CompanyLead).where(CompanyLead.company_id == company_id)).all()
    inputs = company_inputs(company, leads, _board_job_counts(session, {company_id}).get(company_id))
    fit = score_company(inputs)
    stack: list[str] = []
    for posting in inputs.postings:
        for term in sorted(extract_job_technologies(posting.title, posting.description)[0]):
            if term not in stack:
                stack.append(term)
    # Hints are labelled so the model cannot present them as facts.
    description = inputs.description or (
        "(curated-list note, unverified hint) " + " ".join(inputs.lead_notes)[:600] if inputs.lead_notes else None
    )
    facts = CompanyFacts(
        name=company.name,
        website=inputs.website_url,
        stage=fit.stage,
        description=description,
        stack_terms=tuple(stack[:12]),
        posting_titles=tuple(dict.fromkeys(posting.title for posting in inputs.postings))[:8],
        fit_reasons=tuple(f"{factor.name}: {factor.reason}" for factor in fit.factors if factor.points),
        unknowns=fit.unknowns,
    )
    contacts = tuple(
        session.scalars(select(Contact).where(Contact.company_id == company_id).order_by(Contact.created_at)).all()
    )
    return CompanyContext(company=company, fit=fit, facts=facts, contacts=contacts)


def best_contact(contacts: tuple[Contact, ...], *, small_known: bool = False) -> Contact | None:
    """The most relevant stored person for a junior backend candidate (see ``relevance``)."""

    scored = [
        (score, contact)
        for contact in contacts
        if (score := relevance(contact.title, small_known=small_known)) is not None
    ]
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def person_facts(contact: Contact) -> PersonFacts:
    evidence = contact.evidence or {}
    return PersonFacts(
        name=contact.name,
        role=contact.title,
        quote=evidence.get("quote") if isinstance(evidence.get("quote"), str) else None,
        topic=evidence.get("topic") if isinstance(evidence.get("topic"), str) else None,
        source_url=contact.source_url,
    )


def contact_language(contact: Contact, fallback: str) -> str:
    evidence = contact.evidence or {}
    language = evidence.get("language")
    return language if language in {"es", "en"} else fallback


def draft_for_company(
    session: Session,
    company_id: UUID,
    *,
    client: MessagesClient | None,
    language: str = "auto",
    force: bool = False,
    cv_dir: Path = DEFAULT_CV_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
) -> DraftOutcome:
    """Create (or return) the email and LinkedIn DM drafts for one company."""

    context = company_context(session, company_id)
    company, fit = context.company, context.fit
    contact = best_contact(context.contacts, small_known=fit.size.known_small if fit.size else False)
    contact_id = contact.id if contact else None

    existing = {
        channel: find_active_duplicate(
            session,
            company_id=company_id,
            job_id=None,
            contact_id=contact_id,
            purpose=OutreachPurpose.COLD_OUTREACH,
            channel=channel,
        )
        for channel in (OutreachChannel.EMAIL, OutreachChannel.LINKEDIN)
    }
    if all(existing.values()) and not force:
        return DraftOutcome(
            company, fit.stage, "", contact, existing[OutreachChannel.EMAIL], existing[OutreachChannel.LINKEDIN], False
        )
    # Check the inputs before spending a model call.
    resolved_language = resolve_language(
        language,
        contact_language(contact, "") if contact else None,
        context.facts.description,
        default="en",
    )
    base_cv = load_base_cv(resolved_language, cv_dir)
    style_guide = load_style_guide(style_guide_path)
    for old in existing.values():
        if old is None:
            continue
        if not force:
            continue
        try:
            transition_outreach(session, old.id, OutreachStatus.CANCELLED, note="Replaced by a regenerated draft.")
        except InvalidOutreachTransition:
            raise HunterWritingError(
                "An outreach for this company was already sent; it is not replaced. Show it with `outreach show`."
            ) from None

    drafts = generate_company_drafts(
        client,
        context.facts,
        person_facts(contact) if contact else None,
        base_cv=base_cv,
        style_guide=style_guide,
        language=resolved_language,
    )
    rationale = (
        f"Stage: {fit.stage.value}. Overlap used: {drafts.overlap} "
        f"Fit {fit.score}/100 — {fit.explanation()}."
        + (f" Unknown: {', '.join(fit.unknowns)}." if fit.unknowns else "")
        + (f" Contact evidence: {contact.source_url}." if contact and contact.source_url else "")
    )
    recipient_type = contact.contact_type if contact else None
    email = create_outreach(
        session,
        company_id=company_id,
        purpose=OutreachPurpose.COLD_OUTREACH,
        channel=OutreachChannel.EMAIL,
        contact_id=contact_id,
        recipient_contact_type=recipient_type,
        subject=drafts.email_subject,
        body=drafts.email_body,
        recommendation="COMPANY_HUNTER",
        rationale=rationale,
    ).outreach
    linkedin = create_outreach(
        session,
        company_id=company_id,
        purpose=OutreachPurpose.COLD_OUTREACH,
        channel=OutreachChannel.LINKEDIN,
        contact_id=contact_id,
        recipient_contact_type=recipient_type,
        body=drafts.linkedin_dm,
        recommendation="COMPANY_HUNTER",
        rationale=rationale,
    ).outreach
    return DraftOutcome(company, fit.stage, resolved_language, contact, email, linkedin, True)
