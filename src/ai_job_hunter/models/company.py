"""Company entity, independent of any job posting."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.company_evidence import CompanyEvidence
    from ai_job_hunter.models.job import Job


class Company(TimestampMixin, Base):
    """An employer that may have zero or more known jobs."""

    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(Text)

    jobs: Mapped[list[Job]] = relationship("Job", back_populates="company")
    evidence_items: Mapped[list[CompanyEvidence]] = relationship(
        "CompanyEvidence",
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
