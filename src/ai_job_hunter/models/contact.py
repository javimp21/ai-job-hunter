"""Company-scoped contact records backed by explicit source evidence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin


class ContactType(StrEnum):
    RECRUITER = "RECRUITER"
    TALENT = "TALENT"
    HIRING_MANAGER = "HIRING_MANAGER"
    ENGINEERING_MANAGER = "ENGINEERING_MANAGER"
    ENGINEER = "ENGINEER"
    FOUNDER = "FOUNDER"
    OTHER = "OTHER"


_CONTACT_TYPE_VALUES = ", ".join(f"'{value.value}'" for value in ContactType)


class Contact(TimestampMixin, Base):
    """A contact associated with one company; absent facts remain NULL."""

    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_company_id", "company_id"),
        Index("ix_contacts_company_email", "company_id", "email"),
        Index("ix_contacts_company_linkedin", "company_id", "linkedin_url"),
        Index("ix_contacts_source_identity", "company_id", "source_provider", "external_id"),
        # These constraints validate vocabulary only. Identity matching is done
        # by the persistence service, which can return possible matches safely.
        CheckConstraint(
            f"contact_type IN ({_CONTACT_TYPE_VALUES})", name="ck_contacts_contact_type"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    contact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    linkedin_url: Mapped[str | None] = mapped_column(String(2048))
    email: Mapped[str | None] = mapped_column(String(320))
    source_provider: Mapped[str | None] = mapped_column(String(100))
    external_id: Mapped[str | None] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company = relationship("Company")
