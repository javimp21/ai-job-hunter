"""Manual LinkedIn connection queue: the candidate clicks, the tool never touches LinkedIn."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.company import Company
    from ai_job_hunter.models.contact import Contact


class ConnectionRequestStatus(StrEnum):
    SUGGESTED = "SUGGESTED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    SKIPPED = "SKIPPED"


_STATUS_VALUES = ", ".join(f"'{value.value}'" for value in ConnectionRequestStatus)


class ConnectionRequest(TimestampMixin, Base):
    """One suggested connection: person, note, status and dates.

    ``SENT`` and ``ACCEPTED`` only record what the candidate reported after
    acting by hand on LinkedIn; nothing here can send or fetch anything.
    """

    __tablename__ = "connection_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="ck_connection_requests_status"),
        CheckConstraint("language IN ('es', 'en')", name="ck_connection_requests_language"),
        # LinkedIn's connection-note limit, enforced in code and here.
        CheckConstraint("length(note) <= 300", name="ck_connection_requests_note_length"),
        Index("ix_connection_requests_contact_status", "contact_id", "status"),
        Index("ix_connection_requests_company_status", "company_id", "status"),
        Index("ix_connection_requests_suggested_at", "suggested_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConnectionRequestStatus.SUGGESTED.value,
        server_default=ConnectionRequestStatus.SUGGESTED.value,
    )
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    # A LinkedIn post the candidate pasted by hand; the note was regenerated from it.
    grounding_post: Mapped[str | None] = mapped_column(Text)
    follow_up_draft: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[str | None] = mapped_column(String(32))
    suggested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped[Contact] = relationship("Contact")
    company: Mapped[Company] = relationship("Company")
