"""Human review state for canonical jobs, independent of their evaluations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin, UserOwnedMixin, _per_user_unique

if TYPE_CHECKING:
    from ai_job_hunter.models.job import Job


class HumanReviewStatus(StrEnum):
    """User-controlled state for reviewing an opportunity."""

    NEW = "NEW"
    SEEN = "SEEN"
    SAVED = "SAVED"
    DISMISSED = "DISMISSED"


class JobReview(UserOwnedMixin, TimestampMixin, Base):
    """The single mutable human review state associated with one job."""

    __tablename__ = "job_reviews"
    __table_args__ = (
        CheckConstraint(
            "state IN ('NEW', 'SEEN', 'SAVED', 'DISMISSED')", name="ck_job_reviews_state"
        ),
        *_per_user_unique("uq_job_reviews_job", "job_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=HumanReviewStatus.NEW.value, server_default="NEW"
    )
    # Why the job was saved or dismissed (e.g. "salary", "location"); feedback for ranking.
    reason: Mapped[str | None] = mapped_column(String(40))
    reason_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship("Job")
