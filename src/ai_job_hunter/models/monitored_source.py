"""Company job boards the refresh may fetch, with an explicit review lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.company import Company


class MonitoredSourceState(StrEnum):
    """Lifecycle of a discovered board; only ACTIVE boards are fetched.

    Company leads cover the earlier DISCOVERED -> RESOLVED steps. A board is
    created in REVIEW_SOURCE and becomes ACTIVE only by an explicit decision.
    """

    REVIEW_SOURCE = "REVIEW_SOURCE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REJECTED = "REJECTED"


class MonitoredSource(TimestampMixin, Base):
    __tablename__ = "monitored_sources"
    __table_args__ = (
        # identifier_key/region_key are normalized (casefolded, "" for none) so
        # one public board can never be monitored twice.
        UniqueConstraint("provider", "identifier_key", "region_key", name="uq_monitored_source_board"),
        CheckConstraint(
            "state IN ('REVIEW_SOURCE', 'ACTIVE', 'PAUSED', 'REJECTED')",
            name="ck_monitored_sources_state",
        ),
        CheckConstraint("consecutive_failures >= 0", name="ck_monitored_sources_failures"),
        Index("ix_monitored_sources_state_fetched", "state", "last_fetched_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    identifier_key: Mapped[str] = mapped_column(String(512), nullable=False)
    region: Mapped[str | None] = mapped_column(String(32))
    region_key: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    careers_url: Mapped[str | None] = mapped_column(String(2048))
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MonitoredSourceState.REVIEW_SOURCE.value,
        server_default=MonitoredSourceState.REVIEW_SOURCE.value,
    )
    state_reason: Mapped[str | None] = mapped_column(Text)
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How the board was discovered: "career_url" (company lead) or "observed_job_source".
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetch_status: Mapped[str | None] = mapped_column(String(16))
    last_fetch_error: Mapped[str | None] = mapped_column(String(100))
    last_job_count: Mapped[int | None] = mapped_column(Integer)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    preview_stats: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    company: Mapped["Company"] = relationship()
