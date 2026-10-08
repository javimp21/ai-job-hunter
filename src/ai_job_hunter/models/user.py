"""People who use the service: one owner today, more later (docs/MULTIUSER_DESIGN.md)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin


class UserStatus(StrEnum):
    ONBOARDING = "ONBOARDING"  # accepted an invitation, the sign-up conversation is not finished
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"  # the person asked to stop the alerts
    TRIAL_ENDED = "TRIAL_ENDED"  # alerts paused, profile kept for a while
    DELETED = "DELETED"  # personal data removed; the row stays as a tombstone


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_chat_id", name="uq_users_telegram_chat_id"),
        CheckConstraint(
            "status IN ('ONBOARDING', 'ACTIVE', 'PAUSED', 'TRIAL_ENDED', 'DELETED')", name="ck_users_status"
        ),
        Index("ix_users_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="es")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Madrid")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.ACTIVE.value)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_version: Mapped[str | None] = mapped_column(String(20))
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Where the sign-up conversation is and the draft profile so far (cleared when it ends).
    onboarding: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class UserProfile(TimestampMixin, Base):
    """The validated ``CandidateConfig`` of one user, stored as JSON."""

    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profiles_user_id"), Index("ix_user_profiles_sector", "sector"))

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sector: Mapped[str] = mapped_column(String(41), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # A summary of the person's experience (no name, e-mail, phone or address) used to write letters and interview briefs.
    cv_text: Mapped[str | None] = mapped_column(Text)


class Invitation(TimestampMixin, Base):
    """A single-use code the owner gives to one person (closed beta); the person redeems it with /start CODE."""

    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("code", name="uq_invitations_code"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
