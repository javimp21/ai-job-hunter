"""Source-backed facts about a company."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.company import Company


class CompanyEvidence(TimestampMixin, Base):
    """One attributable observation about a company from an external source."""

    __tablename__ = "company_evidence"
    __table_args__ = (
        UniqueConstraint(
            "provider", "evidence_type", "source_key", name="uq_company_evidence_provider_type_key"
        ),
        Index("ix_company_evidence_company_id", "company_id"),
        Index("ix_company_evidence_provider", "provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    external_identifier: Mapped[str | None] = mapped_column(String(512))
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    structured_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped[Company] = relationship("Company", back_populates="evidence_items")
