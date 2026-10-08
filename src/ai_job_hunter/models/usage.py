"""What each person has asked the paid models to write, and what they got (docs/HOSTED_SERVICE_PLAN.md, phase 5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin, UserOwnedMixin


class UsageEvent(UserOwnedMixin, TimestampMixin, Base):
    """One use of a paid model by one person; the quotas count these."""

    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_user_kind_created", "user_id", "kind", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GeneratedDocument(UserOwnedMixin, TimestampMixin, Base):
    """A letter or interview brief written for one person and one job; asking again resends it without paying again."""

    __tablename__ = "generated_documents"
    __table_args__ = (Index("uq_generated_documents_user_job_kind_language", "user_id", "job_id", "kind", "language", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)


class PreferenceChange(UserOwnedMixin, TimestampMixin, Base):
    """One adjustment of a person's alerts learned from their opinions; it can be undone."""

    __tablename__ = "preference_changes"
    __table_args__ = (Index("ix_preference_changes_user_status", "user_id", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="APPLIED")
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
