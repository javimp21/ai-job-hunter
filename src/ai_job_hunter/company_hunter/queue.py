"""Manual LinkedIn connection queue.

The candidate does the clicking on LinkedIn. This module only chooses people
from the verified contacts already stored (point 2 of Company Hunter), writes a
note (at most 300 characters, enforced in code and by a database check) and
records what the candidate reports: sent, accepted or skipped. It never
fetches, scrapes or logs in to linkedin.com.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.ranking import CompanyFit
from ai_job_hunter.company_hunter.relevance import relevance
from ai_job_hunter.company_hunter.service import (
    CompanyContext,
    company_context,
    contact_language,
    person_facts,
)
from ai_job_hunter.company_hunter.writing import (
    DEFAULT_CV_DIR,
    HunterWritingError,
    enforce_note_limit,
    generate_connection_note,
    generate_follow_up,
    load_base_cv,
    load_style_guide,
    resolve_language,
)
from ai_job_hunter.models import ConnectionRequest, ConnectionRequestStatus, Contact
from ai_job_hunter.services.cover_letters import DEFAULT_STYLE_GUIDE_PATH, MessagesClient

DAILY_LIMIT = 5
DEFAULT_DAILY_TARGET = 5
SKIP_DAYS = 60
RESUGGEST_AFTER_DAYS = 14
MAX_CONTACTED_PER_COMPANY = 2
MAX_PER_COMPANY_PER_DAY = 2
SCHEDULE_TZ = ZoneInfo("Europe/Madrid")

_OPEN_STATES = (
    ConnectionRequestStatus.SENT.value,
    ConnectionRequestStatus.ACCEPTED.value,
)


class ConnectionQueueError(ValueError):
    """A safe, user-readable queue error."""


@dataclass(slots=True)
class SuggestionResult:
    today: list[ConnectionRequest] = field(default_factory=list)  # everything suggested today
    new: list[ConnectionRequest] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    reason: str | None = None  # why nothing new was suggested (weekend, cap reached, no eligible contact)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def local_day(value: datetime) -> str:
    return _utc(value).astimezone(SCHEDULE_TZ).date().isoformat()


def is_weekday(now: datetime) -> bool:
    return _utc(now).astimezone(SCHEDULE_TZ).weekday() < 5


def contact_relevance(contact: Contact, *, small_known: bool) -> int | None:
    """Relevance of this stored person for a junior backend candidate; None means never suggest.

    Engineering leaders, tech leads, engineers and tech recruiters qualify. A non-engineering
    C-level person (CEO, CFO, COO, CRO, founders...) qualifies only when the company is known,
    from evidence, to have at most 50 people; for larger or unknown-size companies never.
    """

    return relevance(contact.title, small_known=small_known)


def requests_today(session: Session, now: datetime) -> list[ConnectionRequest]:
    today = local_day(now)
    since = _utc(now) - timedelta(days=2)
    rows = session.scalars(
        select(ConnectionRequest).where(ConnectionRequest.suggested_at >= since).order_by(
            ConnectionRequest.suggested_at, ConnectionRequest.id
        )
    ).all()
    return [row for row in rows if local_day(row.suggested_at) == today]


def contacted_counts(session: Session) -> dict[UUID, int]:
    counts: dict[UUID, int] = {}
    for company_id in session.scalars(
        select(ConnectionRequest.company_id).where(ConnectionRequest.status.in_(_OPEN_STATES))
    ).all():
        counts[company_id] = counts.get(company_id, 0) + 1
    return counts


def _blocked_contacts(session: Session, now: datetime) -> set[UUID]:
    """Contacts that must not be suggested now: contacted, skipped < 60 days ago, or suggested recently."""

    blocked: set[UUID] = set()
    recent = _utc(now) - timedelta(days=RESUGGEST_AFTER_DAYS)
    for row in session.scalars(select(ConnectionRequest)).all():
        if row.status in _OPEN_STATES:
            blocked.add(row.contact_id)
        elif row.status == ConnectionRequestStatus.SKIPPED.value:
            if row.skip_until is None or _utc(row.skip_until) > _utc(now):
                blocked.add(row.contact_id)
        elif _utc(row.suggested_at) > recent:  # SUGGESTED and not yet answered
            blocked.add(row.contact_id)
    return blocked


def eligible_contacts(
    session: Session, ranked: Sequence[CompanyFit], now: datetime
) -> list[tuple[CompanyFit, Contact, int]]:
    """Verified contacts at ranked companies, best company first, then most relevant role."""

    blocked = _blocked_contacts(session, now)
    contacted = contacted_counts(session)
    out: list[tuple[CompanyFit, Contact, int]] = []
    for fit in ranked:
        if contacted.get(fit.company_id, 0) >= MAX_CONTACTED_PER_COMPANY:
            continue
        contacts = session.scalars(
            select(Contact).where(Contact.company_id == fit.company_id).order_by(Contact.created_at, Contact.id)
        ).all()
        small_known = fit.size.known_small if fit.size is not None else False
        scored = [
            (priority, contact)
            for contact in contacts
            if contact.id not in blocked and (priority := contact_relevance(contact, small_known=small_known)) is not None
        ]
        scored.sort(key=lambda item: -item[0])
        out.extend((fit, contact, priority) for priority, contact in scored)
    return out


def suggest_connections(
    session: Session,
    ranked: Sequence[CompanyFit],
    *,
    client: MessagesClient | None,
    now: datetime | None = None,
    target: int = DEFAULT_DAILY_TARGET,
    allow_weekend: bool = False,
    cv_dir: Path = DEFAULT_CV_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
) -> SuggestionResult:
    """Choose up to ``target`` (never more than 5 per day in total) people and write their notes."""

    current = _utc(now or datetime.now(UTC))
    target = max(1, min(target, DAILY_LIMIT))
    result = SuggestionResult(today=requests_today(session, current))
    if not allow_weekend and not is_weekday(current):
        result.reason = "weekend: no suggestions"
        return result
    remaining = target - len(result.today)
    if remaining <= 0:
        result.reason = f"already {len(result.today)} suggestion(s) today"
        return result

    eligible = eligible_contacts(session, ranked, current)
    if not eligible:
        result.reason = "no eligible verified contact (run `outreach find-contacts` for the top companies)"
        return result

    per_company: dict[UUID, int] = {}
    for row in result.today:
        per_company[row.company_id] = per_company.get(row.company_id, 0) + 1
    contexts: dict[UUID, CompanyContext] = {}
    attempts = 0
    for fit, contact, _priority in eligible:
        if remaining <= 0 or attempts >= target * 2:
            break
        if per_company.get(fit.company_id, 0) >= MAX_PER_COMPANY_PER_DAY:
            continue
        attempts += 1
        try:
            context = contexts.get(fit.company_id) or company_context(session, fit.company_id)
            contexts[fit.company_id] = context
            language = resolve_language(
                contact_language(contact, ""),
                (contact.evidence or {}).get("topic") if contact.evidence else None,
                (contact.evidence or {}).get("quote") if contact.evidence else None,
                default="en",
            )
            note = generate_connection_note(
                client,
                context.facts,
                person_facts(contact),
                base_cv=load_base_cv(language, cv_dir),
                style_guide=load_style_guide(style_guide_path),
                language=language,
            )
            request = ConnectionRequest(
                contact_id=contact.id,
                company_id=fit.company_id,
                status=ConnectionRequestStatus.SUGGESTED.value,
                language=language,
                note=enforce_note_limit(note),
                suggested_at=current,
            )
        except HunterWritingError as error:
            result.failures.append(f"{contact.name} ({fit.name}): {error}")
            continue
        session.add(request)
        session.flush()
        result.new.append(request)
        result.today.append(request)
        per_company[fit.company_id] = per_company.get(fit.company_id, 0) + 1
        remaining -= 1
    if not result.new and result.reason is None:
        result.reason = "no note could be written" if result.failures else "no eligible verified contact"
    return result


# --------------------------------------------------------------------------------------
# Status changes reported by the candidate


def get_request(session: Session, request_id: UUID) -> ConnectionRequest:
    request = session.get(ConnectionRequest, request_id)
    if request is None:
        raise ConnectionQueueError("Connection request not found.")
    return request


def mark_sent(session: Session, request_id: UUID, *, now: datetime | None = None) -> ConnectionRequest:
    """The candidate reports they sent the request by hand; idempotent."""

    request = get_request(session, request_id)
    if request.status in _OPEN_STATES:
        return request
    request.status = ConnectionRequestStatus.SENT.value
    request.sent_at = _utc(now or datetime.now(UTC))
    request.skipped_at = None
    request.skip_until = None
    session.flush()
    return request


def mark_accepted(session: Session, request_id: UUID, *, now: datetime | None = None) -> ConnectionRequest:
    request = get_request(session, request_id)
    if request.status == ConnectionRequestStatus.ACCEPTED.value:
        return request
    request.status = ConnectionRequestStatus.ACCEPTED.value
    request.accepted_at = _utc(now or datetime.now(UTC))
    request.skipped_at = None
    request.skip_until = None
    session.flush()
    return request


def mark_skipped(session: Session, request_id: UUID, *, now: datetime | None = None) -> ConnectionRequest:
    """Do not suggest this person again for 60 days; a request already sent cannot be skipped."""

    request = get_request(session, request_id)
    if request.status in _OPEN_STATES:
        raise ConnectionQueueError("This request was already sent; it cannot be skipped.")
    if request.status == ConnectionRequestStatus.SKIPPED.value:
        return request
    current = _utc(now or datetime.now(UTC))
    request.status = ConnectionRequestStatus.SKIPPED.value
    request.skipped_at = current
    request.skip_until = current + timedelta(days=SKIP_DAYS)
    session.flush()
    return request


def regenerate_note_from_post(
    session: Session,
    request_id: UUID,
    post: str,
    *,
    client: MessagesClient | None,
    cv_dir: Path = DEFAULT_CV_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
) -> ConnectionRequest:
    """Rewrite the note grounded in a LinkedIn post the candidate pasted by hand."""

    request = get_request(session, request_id)
    if request.status != ConnectionRequestStatus.SUGGESTED.value:
        raise ConnectionQueueError("Only a suggested (not yet sent) request can be regenerated.")
    context = company_context(session, request.company_id)
    contact = session.get(Contact, request.contact_id)
    note = generate_connection_note(
        client,
        context.facts,
        person_facts(contact),
        base_cv=load_base_cv(request.language, cv_dir),
        style_guide=load_style_guide(style_guide_path),
        language=request.language,
        post=post,
    )
    request.note = enforce_note_limit(note)
    request.grounding_post = post.strip()[:4000]
    session.flush()
    return request


def build_follow_up(
    session: Session,
    request_id: UUID,
    *,
    client: MessagesClient | None,
    cv_dir: Path = DEFAULT_CV_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
) -> str:
    """The first casual message after the connection is accepted; generated once and stored."""

    request = get_request(session, request_id)
    if request.follow_up_draft:
        return request.follow_up_draft
    context = company_context(session, request.company_id)
    contact = session.get(Contact, request.contact_id)
    draft = generate_follow_up(
        client,
        context.facts,
        person_facts(contact),
        base_cv=load_base_cv(request.language, cv_dir),
        style_guide=load_style_guide(style_guide_path),
        language=request.language,
        previous_note=request.note,
    )
    request.follow_up_draft = draft
    session.flush()
    return draft


def public_linkedin_url(contact: Contact) -> str | None:
    """A profile URL only when a public non-LinkedIn page we fetched linked to it (stored at discovery)."""

    return contact.linkedin_url
