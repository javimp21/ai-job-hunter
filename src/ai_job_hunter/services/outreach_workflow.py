"""Orchestration for explicit, local-only outreach draft creation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.models import Company, Job, Outreach
from ai_job_hunter.models.contact import ContactType
from ai_job_hunter.models.outreach import (
    OutreachChannel,
    OutreachPurpose,
    OutreachStatus,
)
from ai_job_hunter.outreach import (
    DraftChannel,
    DraftTemplate,
    OutreachRecommendation,
    generate_draft,
    load_candidate_projects,
    outreach_recommendation_reasons,
    recommend_contact_strategy,
)
from ai_job_hunter.services.opportunities import (
    Opportunity,
    list_opportunities,
)
from ai_job_hunter.services.outreach_persistence import (
    OutreachCreateResult,
    OutreachPersistenceError,
    create_outreach,
    list_outreaches,
)


@dataclass(frozen=True, slots=True)
class OutreachPlan:
    """The policy and contact-role explanation for one opportunity."""

    opportunity: Opportunity
    recommendation_reasons: tuple[str, ...]
    preferred_contact_types: tuple[str, ...]
    contact_strategy_reasons: tuple[str, ...]


def plan_outreach_for_job(
    session: Session,
    job_id: UUID,
    candidate: CandidateConfig,
) -> OutreachPlan | None:
    """Read the current opportunity and prepare an independent outreach plan."""

    opportunity = _find_opportunity(session, job_id, candidate)
    if opportunity is None:
        return None
    role_relevance = _signal_value(opportunity.jev_signals, "role_relevance")
    active_exists = _has_active_job_outreach(session, job_id)
    reasons = outreach_recommendation_reasons(
        opportunity.decision,
        opportunity.priority,
        role_relevance,
        _has_strong_mismatch(opportunity.deterministic_result),
        opportunity.application_status.value if opportunity.application_status else None,
        active_exists,
    )
    strategy = recommend_contact_strategy(opportunity.title)
    return OutreachPlan(
        opportunity=opportunity,
        recommendation_reasons=reasons,
        preferred_contact_types=tuple(item.value for item in strategy.preferred_contact_types),
        contact_strategy_reasons=strategy.reasons,
    )


def create_initial_outreach_drafts(
    session: Session,
    job_id: UUID,
    candidate: CandidateConfig,
    *,
    projects_path: str | Path | None = None,
    channel: DraftChannel | str = DraftChannel.LINKEDIN,
) -> tuple[OutreachCreateResult, ...]:
    """Create recruiter and engineer/referral drafts, never contacts or messages.

    If active outreach already exists for this job, return those rows without
    creating another draft. Callers own and commit the surrounding transaction.
    """

    opportunity = _find_opportunity(session, job_id, candidate)
    if opportunity is None:
        raise OutreachPersistenceError("Job has no current opportunity to draft against.")

    existing = tuple(
        item
        for item in list_outreaches(session, job_id=job_id)
        if item.status
        in {
            OutreachStatus.DRAFT.value,
            OutreachStatus.APPROVED.value,
            OutreachStatus.SENT.value,
            OutreachStatus.REPLIED.value,
        }
    )
    if existing:
        return tuple(OutreachCreateResult(outreach=item, created=False) for item in existing)

    if opportunity.outreach_recommendation is OutreachRecommendation.NO_OUTREACH:
        raise OutreachPersistenceError(
            "Outreach recommendation is NO_OUTREACH; no initial draft was created."
        )

    job = session.get(Job, job_id)
    if job is None or job.company_id is None:
        raise OutreachPersistenceError("Job has no linked company for outreach persistence.")
    company = session.get(Company, job.company_id)
    if company is None:
        raise OutreachPersistenceError("Job company does not exist.")

    projects = load_candidate_projects(projects_path)
    recommendation = opportunity.outreach_recommendation.value
    rationale = "\n".join(
        (
            *outreach_recommendation_reasons(
                opportunity.decision,
                opportunity.priority,
                _signal_value(opportunity.jev_signals, "role_relevance"),
                _has_strong_mismatch(opportunity.deterministic_result),
                opportunity.application_status.value if opportunity.application_status else None,
                existing_active_outreach=False,
            ),
            "No contact identity was supplied; this draft is addressed to a role placeholder.",
        )
    )

    templates = (
        (
            DraftTemplate.RECRUITER_INTRO,
            OutreachPurpose.RECRUITER_INTRO,
            ContactType.RECRUITER,
        ),
        (
            DraftTemplate.ENGINEER_REFERRAL,
            OutreachPurpose.REFERRAL,
            ContactType.ENGINEER,
        ),
    )
    results: list[OutreachCreateResult] = []
    for template, purpose, recipient_type in templates:
        draft = generate_draft(
            template=template,
            channel=channel,
            company=company.name,
            job_title=opportunity.title,
            job_technologies=(
                *opportunity.technologies,
                *opportunity.required_technologies,
            ),
            candidate_profile=candidate.profile,
            candidate_projects=projects,
        )
        result = create_outreach(
            session,
            company_id=company.id,
            job_id=job.id,
            purpose=purpose,
            channel=OutreachChannel(draft.channel.value),
            recipient_contact_type=recipient_type,
            subject=draft.subject,
            body=draft.body,
            recommendation=recommendation,
            rationale=rationale,
            automatic=True,
        )
        results.append(result)
    return tuple(results)


def _find_opportunity(
    session: Session,
    job_id: UUID,
    candidate: CandidateConfig,
) -> Opportunity | None:
    return next(
        (
            item
            for item in list_opportunities(
                session,
                candidate,
                limit=10000,
                include_applied=True,
                include_skip=True,
            )
            if item.job_id == job_id
        ),
        None,
    )


def _has_active_job_outreach(session: Session, job_id: UUID) -> bool:
    return any(
        item.status
        in {
            OutreachStatus.DRAFT.value,
            OutreachStatus.APPROVED.value,
            OutreachStatus.SENT.value,
            OutreachStatus.REPLIED.value,
        }
        for item in list_outreaches(session, job_id=job_id)
    )


def _signal_value(signals: dict[str, object] | None, name: str) -> float | None:
    if not isinstance(signals, dict):
        return None
    value = signals.get(name)
    if not isinstance(value, dict):
        return None
    score = value.get("value")
    if not isinstance(score, (float, int)) or isinstance(score, bool):
        return None
    return float(score)


def _has_strong_mismatch(deterministic_result: dict[str, object] | None) -> bool:
    if not isinstance(deterministic_result, dict):
        return False
    signals = deterministic_result.get("signals")
    technology = signals.get("technology") if isinstance(signals, dict) else None
    mismatches = technology.get("critical_mismatches") if isinstance(technology, dict) else None
    return isinstance(mismatches, (list, tuple)) and bool(mismatches)
