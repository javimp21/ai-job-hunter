"""Evaluation of the user's free-text opinions about alerts.

The notes written as replies to alerts (``feedback_notes``) are gathered with the facts of each offer and its vote, and
Claude reads them to say what keeps repeating and which change to the filters, weights or rubric would follow from it.
Nothing is applied: the result is a short Spanish message with proposals the user approves, since an opinion about one
offer is a hint and not a rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ai_job_hunter.models import Job, OpportunityNotification, ReportDelivery
from ai_job_hunter.models.job_feedback import JobFeedbackNote
from ai_job_hunter.services.cover_letters import CoverLetterError, _anthropic_client

REVIEW_KIND = "FEEDBACK"
REVIEW_MODEL = "claude-sonnet-5-5"
MAX_NOTES = 60
MAX_DESCRIPTION_CHARS = 600

_SYSTEM_PROMPT = """You help one job seeker tune a personal job-alert tool. You get the free-text opinions they wrote
about alerts, each with the offer's facts, the tool's decision and priority, and the vote they gave (SAVED = thumbs up,
DISMISSED = thumbs down, none = no vote). Write in Spanish, concise, for a Telegram message (under 1800 characters, plain
text, no markdown tables).

Structure:
1. "Lo que se repite": the 3 to 5 themes that appear in more than one note (stack, salary, location, experience asked,
   seniority, company type, role, language, work mode, description quality...). For each, say whether it is a like or a
   dislike and how many notes support it. A theme with a single note is a "dato suelto", not a pattern.
2. "Cambios que propongo": for each pattern, one concrete change to the tool: a priority bonus or penalty, a hard filter,
   a wording change in the Jev rubric, a lower or higher alert bar, or "nada: es una excepción". Say what evidence
   supports it and what could go wrong (offers it would hide).
3. "Dudas": what you cannot tell from the notes and one question to ask the user.

Never invent facts that are not in the notes or offer data. Opinions are hints, not rules: propose, do not decide. If
the notes contradict each other, say so."""


@dataclass(frozen=True, slots=True)
class FeedbackItem:
    job_id: str
    note: str
    vote: str | None
    title: str
    company: str
    location: str | None
    remote_policy: str | None
    decision: str | None
    priority: int | None
    description: str


@dataclass(frozen=True, slots=True)
class FeedbackReview:
    status: str  # "reviewed" | "not_enough_notes" | "failed"
    notes: int = 0
    message: str | None = None


def collect_notes(session: Session, *, since: datetime | None, limit: int = MAX_NOTES) -> list[FeedbackItem]:
    query = select(JobFeedbackNote).options(joinedload(JobFeedbackNote.job).joinedload(Job.company))
    if since is not None:
        query = query.where(JobFeedbackNote.created_at > since)
    notes = list(session.scalars(query.order_by(JobFeedbackNote.created_at.desc()).limit(limit)).unique())
    items: list[FeedbackItem] = []
    for note in notes:
        job = note.job
        alert = session.execute(
            select(OpportunityNotification.decision, OpportunityNotification.priority)
            .where(OpportunityNotification.job_id == note.job_id, OpportunityNotification.channel == "TELEGRAM")
            .order_by(OpportunityNotification.created_at.desc())
            .limit(1)
        ).first()
        items.append(
            FeedbackItem(
                job_id=str(note.job_id),
                note=note.text,
                vote=note.vote,
                title=job.title,
                company=job.company.name if job.company is not None else "",
                location=job.location,
                remote_policy=job.remote_policy,
                decision=alert[0] if alert else None,
                priority=alert[1] if alert else None,
                description=(job.description or "")[:MAX_DESCRIPTION_CHARS],
            )
        )
    return items


def build_request(items: Sequence[FeedbackItem], tuning_summary: str) -> dict[str, Any]:
    lines = [f"Current tool settings: {tuning_summary}", f"Notes: {len(items)}", ""]
    for index, item in enumerate(items, 1):
        lines += [
            f"[{index}] vote={item.vote or 'none'} decision={item.decision or '?'} priority={item.priority}",
            f"    offer: {item.title} @ {item.company} | {item.location or 'no location'} | {item.remote_policy or 'mode unknown'}",
            f"    opinion: {item.note}",
            f"    posting start: {item.description!r}",
            "",
        ]
    return {
        "model": REVIEW_MODEL,
        "max_tokens": 1500,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": "\n".join(lines)}],
    }


def _last_review(session: Session) -> datetime | None:
    value = session.scalar(select(func.max(ReportDelivery.sent_at)).where(ReportDelivery.kind == REVIEW_KIND))
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def review_notes(
    session: Session,
    *,
    tuning_summary: str,
    min_notes: int = 5,
    client: Any | None = None,
    now: datetime | None = None,
    closing: str = "No he cambiado nada: dime qué propuestas quieres aplicar.",
) -> FeedbackReview:
    """Read the notes written since the last review; with fewer than ``min_notes`` nothing is sent or spent."""

    items = collect_notes(session, since=_last_review(session))
    if len(items) < min_notes:
        return FeedbackReview("not_enough_notes", notes=len(items))
    try:
        active = client or _anthropic_client()
        response = active.messages.create(**build_request(items, tuning_summary))
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
    except CoverLetterError:
        return FeedbackReview("failed", notes=len(items))
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing
        return FeedbackReview("failed", notes=len(items))
    if not text:
        return FeedbackReview("failed", notes=len(items))
    message = f"📝 Lo que me has contado ({len(items)} notas)\n\n{text}\n\n{closing}"
    return FeedbackReview("reviewed", notes=len(items), message=message)


def mark_reviewed(session: Session, *, now: datetime | None = None) -> None:
    """Record that the notes up to now were reviewed and delivered (called only after Telegram accepted the message)."""

    moment = now or datetime.now(UTC)
    session.add(ReportDelivery(kind=REVIEW_KIND, period_start=moment, period_end=moment, sent_at=moment))
    session.commit()
