"""Free-text opinions about alerts: a reply to an alert (or to the bot's question after a vote) is stored as a note."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.models import JobReview, OpportunityNotification
from ai_job_hunter.models.job_feedback import FeedbackPrompt, JobFeedbackNote

MAX_NOTE_CHARS = 2000
_VOTES = {"SAVED", "DISMISSED"}


def job_for_alert_message(session: Session, message_id: int) -> UUID | None:
    """The job of the Telegram alert with this message id, if it was one of ours."""

    return session.scalar(
        select(OpportunityNotification.job_id)
        .where(OpportunityNotification.provider_message_id == str(message_id), OpportunityNotification.channel == "TELEGRAM")
        .limit(1)
    )


class DbPrompts:
    """Message id of the bot's question after a vote -> its job, kept in the database so it survives a restart.

    It behaves like the dictionary the bot code already uses (``prompts[id] = job_id`` and ``prompts.get(id)``); the
    rows belong to the acting person, so each one only finds their own questions.
    """

    def __init__(self, session_factory) -> None:  # noqa: ANN001 - a callable returning a Session
        self._sessions = session_factory

    def __setitem__(self, message_id: int, job_id: UUID) -> None:
        with self._sessions() as session:
            if session.scalar(select(FeedbackPrompt.id).where(FeedbackPrompt.message_id == message_id)) is None:
                session.add(FeedbackPrompt(message_id=message_id, job_id=job_id))
                session.commit()

    def get(self, message_id: int, default: UUID | None = None) -> UUID | None:
        with self._sessions() as session:
            found = session.scalar(select(FeedbackPrompt.job_id).where(FeedbackPrompt.message_id == message_id))
        return found if found is not None else default


def add_note(session: Session, job_id: UUID, text: str) -> JobFeedbackNote | None:
    """Store one opinion (trimmed, capped); empty text stores nothing. Keeps the vote the job has now."""

    cleaned = text.strip()[:MAX_NOTE_CHARS]
    if not cleaned:
        return None
    state = session.scalar(select(JobReview.state).where(JobReview.job_id == job_id))
    note = JobFeedbackNote(job_id=job_id, text=cleaned, vote=state if state in _VOTES else None)
    session.add(note)
    session.flush()
    return note


def list_notes(session: Session, *, limit: int = 100) -> list[JobFeedbackNote]:
    return list(session.scalars(select(JobFeedbackNote).order_by(JobFeedbackNote.created_at.desc()).limit(limit)))
