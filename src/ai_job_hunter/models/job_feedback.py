"""Free-text opinions the user writes about an alert (what is good, what is bad), with or without a 👍/👎."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.job import Job
from ai_job_hunter.models.mixins import TimestampMixin


class JobFeedbackNote(TimestampMixin, Base):
    __tablename__ = "job_feedback_notes"
    __table_args__ = (Index("ix_job_feedback_notes_job_id", "job_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    job: Mapped["Job"] = relationship()
    # The vote the job had when the note was written: SAVED (👍), DISMISSED (👎) or none.
    vote: Mapped[str | None] = mapped_column(String(20))
