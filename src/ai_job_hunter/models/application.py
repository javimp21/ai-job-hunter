"""Application lifecycle and explicit status-change history."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.job import Job


class ApplicationStatus(StrEnum):
    """Allowed lifecycle states for a user-managed application."""

    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


_APPLICATION_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in ApplicationStatus)


class Application(TimestampMixin, Base):
    """An application the user is tracking for a single canonical job."""

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_APPLICATION_STATUS_VALUES})", name="ck_applications_status"
        ),
        Index("ix_applications_status", "status"),
        UniqueConstraint("job_id", name="uq_applications_job_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ApplicationStatus.DRAFT.value,
        server_default=ApplicationStatus.DRAFT.value,
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(String(2048))
    cv_version: Mapped[str | None] = mapped_column(String(255))

    job: Mapped[Job] = relationship("Job")
    events: Mapped[list[ApplicationEvent]] = relationship(
        "ApplicationEvent",
        back_populates="application",
        passive_deletes="all",
        order_by="ApplicationEvent.occurred_at, ApplicationEvent.id",
    )


class ApplicationEvent(Base):
    """An explicit history entry for one application lifecycle event."""

    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_APPLICATION_STATUS_VALUES})",
            name="ck_application_events_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({_APPLICATION_STATUS_VALUES})", name="ck_application_events_to_status"
        ),
        Index("ix_application_events_application_occurred", "application_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("applications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, default="STATUS_CHANGED")
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped[Application] = relationship("Application", back_populates="events")
