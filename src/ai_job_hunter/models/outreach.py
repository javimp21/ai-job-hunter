"""Persisted outreach drafts and append-only lifecycle history."""

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
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.contact import ContactType
from ai_job_hunter.models.mixins import TimestampMixin, UserOwnedMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.application import Application
    from ai_job_hunter.models.company import Company
    from ai_job_hunter.models.contact import Contact
    from ai_job_hunter.models.job import Job


class OutreachPurpose(StrEnum):
    REFERRAL = "REFERRAL"
    RECRUITER_INTRO = "RECRUITER_INTRO"
    HIRING_MANAGER_INTRO = "HIRING_MANAGER_INTRO"
    JOB_INTEREST = "JOB_INTEREST"
    COLD_OUTREACH = "COLD_OUTREACH"


class OutreachChannel(StrEnum):
    EMAIL = "EMAIL"
    LINKEDIN = "LINKEDIN"
    OTHER = "OTHER"


class OutreachStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT = "SENT"
    REPLIED = "REPLIED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"
    CANCELLED = "CANCELLED"


class OutreachEventType(StrEnum):
    CREATED = "CREATED"
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT = "SENT"
    REPLIED = "REPLIED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"
    CANCELLED = "CANCELLED"
    NOTE_ADDED = "NOTE_ADDED"


_PURPOSE_VALUES = ", ".join(f"'{value.value}'" for value in OutreachPurpose)
_CHANNEL_VALUES = ", ".join(f"'{value.value}'" for value in OutreachChannel)
_STATUS_VALUES = ", ".join(f"'{value.value}'" for value in OutreachStatus)
_EVENT_TYPE_VALUES = ", ".join(f"'{value.value}'" for value in OutreachEventType)
_ACTIVE_STATUSES_SQL = "'DRAFT', 'APPROVED', 'SENT', 'REPLIED'"
_CONTACT_TYPE_VALUES = ", ".join(f"'{value.value}'" for value in ContactType)


class Outreach(UserOwnedMixin, TimestampMixin, Base):
    """A human-reviewable outreach record; this model cannot send messages."""

    __tablename__ = "outreaches"
    __table_args__ = (
        CheckConstraint(f"purpose IN ({_PURPOSE_VALUES})", name="ck_outreaches_purpose"),
        CheckConstraint(f"channel IN ({_CHANNEL_VALUES})", name="ck_outreaches_channel"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="ck_outreaches_status"),
        CheckConstraint(
            f"recipient_contact_type IS NULL OR recipient_contact_type IN ({_CONTACT_TYPE_VALUES})",
            name="ck_outreaches_recipient_contact_type",
        ),
        Index("ix_outreaches_company_status", "company_id", "status"),
        Index("ix_outreaches_job_id", "job_id"),
        Index("ix_outreaches_contact_id", "contact_id"),
        Index("ix_outreaches_application_id", "application_id"),
        # A family of partial unique indexes covers nullable job/contact fields
        # without relying on SQL NULL's database-specific uniqueness behavior.
        Index(
            "uq_outreach_active_job_contact_purpose",
            "job_id",
            "contact_id",
            "purpose",
            unique=True,
            sqlite_where=text(
                f"job_id IS NOT NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
            postgresql_where=text(
                f"job_id IS NOT NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
        ),
        Index(
            "uq_outreach_active_job_without_contact_purpose",
            "job_id",
            "purpose",
            unique=True,
            sqlite_where=text(
                f"job_id IS NOT NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
            postgresql_where=text(
                f"job_id IS NOT NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
        ),
        Index(
            "uq_outreach_active_company_contact_purpose",
            "company_id",
            "contact_id",
            "channel",
            "purpose",
            unique=True,
            sqlite_where=text(
                f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
            postgresql_where=text(
                f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
        ),
        Index(
            "uq_outreach_active_company_without_contact_purpose",
            "company_id",
            "channel",
            "purpose",
            unique=True,
            sqlite_where=text(
                f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
            postgresql_where=text(
                f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES_SQL})"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=True
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=True
    )
    application_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("applications.id", ondelete="RESTRICT"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OutreachStatus.DRAFT.value,
        server_default=OutreachStatus.DRAFT.value,
    )
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    recipient_contact_type: Mapped[str | None] = mapped_column(String(32))
    recommendation: Mapped[str | None] = mapped_column(String(32))
    rationale: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship("Company")
    job: Mapped[Job | None] = relationship("Job")
    contact: Mapped[Contact | None] = relationship("Contact")
    application: Mapped[Application | None] = relationship("Application")
    events: Mapped[list[OutreachEvent]] = relationship(
        "OutreachEvent",
        back_populates="outreach",
        order_by="OutreachEvent.occurred_at, OutreachEvent.id",
        passive_deletes="all",
    )


class OutreachEvent(Base):
    """Immutable record of one outreach creation, transition, or note.

    ORM listeners reject updates/deletes. Privileged direct SQL can bypass
    those Python-level guards and must be treated as administrative access.
    """

    __tablename__ = "outreach_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPE_VALUES})", name="ck_outreach_events_event_type"
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_STATUS_VALUES})",
            name="ck_outreach_events_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({_STATUS_VALUES})", name="ck_outreach_events_to_status"
        ),
        Index("ix_outreach_events_outreach_occurred", "outreach_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    outreach_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("outreaches.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    outreach: Mapped[Outreach] = relationship("Outreach", back_populates="events")


@event.listens_for(OutreachEvent, "before_update")
def _reject_event_update(_mapper: object, _connection: object, _target: OutreachEvent) -> None:
    raise ValueError("OutreachEvent history is append-only.")


@event.listens_for(OutreachEvent, "before_delete")
def _reject_event_delete(_mapper: object, _connection: object, _target: OutreachEvent) -> None:
    raise ValueError("OutreachEvent history is append-only.")
