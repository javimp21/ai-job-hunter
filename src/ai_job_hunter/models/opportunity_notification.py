"""Delivery ledger for opportunity notifications."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin, UserOwnedMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.job import Job


class OpportunityNotificationStatus(StrEnum):
    """Local ledger state for one evaluation/channel notification."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"


class OpportunityNotification(UserOwnedMixin, TimestampMixin, Base):
    """One safe-to-send message keyed to a specific evaluated opportunity."""

    __tablename__ = "opportunity_notifications"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "evaluation_fingerprint",
            "channel",
            name="uq_opportunity_notifications_eval_channel",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'SUPPRESSED')",
            name="ck_opportunity_notifications_status",
        ),
        CheckConstraint(
            "decision IN ('APPLY', 'REVIEW', 'SKIP')",
            name="ck_opportunity_notifications_decision",
        ),
        CheckConstraint(
            "channel IN ('TELEGRAM', 'TELEGRAM_DIGEST')", name="ck_opportunity_notifications_channel"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_opportunity_notifications_attempt_count"),
        Index("ix_opportunity_notifications_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="TELEGRAM")
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OpportunityNotificationStatus.PENDING.value
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dispatch_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    failure_reason: Mapped[str | None] = mapped_column(String(100))
    suppression_reason: Mapped[str | None] = mapped_column(String(100))
    provider_message_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship("Job")
