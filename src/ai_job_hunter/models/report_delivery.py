"""Idempotency marker for periodic Telegram reports (not tied to any job)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin, UserOwnedMixin


class ReportDelivery(UserOwnedMixin, TimestampMixin, Base):
    """One successfully delivered report, e.g. kind ``WEEKLY``.

    The notification ledger requires a job per row, so a report that covers
    many jobs keeps its own marker instead of borrowing an unrelated job id.
    """

    __tablename__ = "report_deliveries"
    __table_args__ = (Index("ix_report_deliveries_kind_sent", "kind", "sent_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
