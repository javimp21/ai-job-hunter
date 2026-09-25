"""A source-specific occurrence of a canonical job."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base

if TYPE_CHECKING:
    from ai_job_hunter.models.job import Job


class JobSource(Base):
    """Traceability data for one provider's representation of a job."""

    __tablename__ = "job_sources"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_job_sources_provider_external_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(512))
    original_url: Mapped[str | None] = mapped_column(String(2048))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    company_website: Mapped[str | None] = mapped_column(String(2048))
    source_title: Mapped[str | None] = mapped_column(String(255))
    source_description: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(String(255))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(20))
    employment_type: Mapped[str | None] = mapped_column(String(30))
    remote_policy: Mapped[str | None] = mapped_column(String(20))
    remote_eligibility: Mapped[str | None] = mapped_column(String(30))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    job: Mapped[Job] = relationship("Job", back_populates="sources")
