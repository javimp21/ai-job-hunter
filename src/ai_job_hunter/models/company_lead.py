"""Persisted discovery leads for companies not yet present in job sources."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.company import Company


class CompanyLeadStatus(StrEnum):
    NEW = "NEW"
    RESOLVED = "RESOLVED"
    SUPPORTED_ATS = "SUPPORTED_ATS"
    UNSUPPORTED_ATS = "UNSUPPORTED_ATS"
    NO_CAREERS_PAGE = "NO_CAREERS_PAGE"
    AMBIGUOUS = "AMBIGUOUS"
    FAILED = "FAILED"


class CompanyLead(TimestampMixin, Base):
    """Source-attributed company discovery input and its resolution state."""

    __tablename__ = "company_leads"
    __table_args__ = (
        UniqueConstraint("normalized_name", "domain_key", name="uq_company_lead_name_domain"),
        Index("ix_company_leads_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Empty string is the explicit no-domain identity and permits a portable unique key.
    domain_key: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    website_url: Mapped[str | None] = mapped_column(String(2048))
    careers_url: Mapped[str | None] = mapped_column(String(2048))
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    location_hint: Mapped[str | None] = mapped_column(String(255))
    hiring_hint: Mapped[str | None] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text)
    source_provenance: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CompanyLeadStatus.NEW.value, server_default="NEW"
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    ats_provider: Mapped[str | None] = mapped_column(String(32))
    ats_identifier: Mapped[str | None] = mapped_column(String(512))
    ats_region: Mapped[str | None] = mapped_column(String(32))

    company: Mapped[Company | None] = relationship("Company")
