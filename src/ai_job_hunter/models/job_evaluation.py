"""Versioned evaluation output associated with a canonical job."""

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
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_hunter.db.base import Base
from ai_job_hunter.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from ai_job_hunter.models.job import Job


class EvaluationStatus(StrEnum):
    """Whether a saved evaluation is queued or has a final result."""

    PENDING = "PENDING"
    EVALUATED = "EVALUATED"


class JobEvaluation(TimestampMixin, Base):
    """One versioned deterministic and optional Jev evaluation for a job."""

    __tablename__ = "job_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "evaluation_fingerprint", name="uq_job_evaluations_job_fingerprint"
        ),
        Index("ix_job_evaluations_rubric_version", "rubric_version"),
        CheckConstraint(
            "status IN ('PENDING', 'EVALUATED')", name="ck_job_evaluations_status"
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('APPLY', 'REVIEW', 'SKIP')",
            name="ck_job_evaluations_decision",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND decision IS NULL AND evaluated_at IS NULL) OR "
            "(status = 'EVALUATED' AND decision IS NOT NULL AND evaluated_at IS NOT NULL)",
            name="ck_job_evaluations_completion_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EvaluationStatus.PENDING.value, server_default="PENDING"
    )
    decision: Mapped[str | None] = mapped_column(String(16))
    rubric_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_configuration: Mapped[str | None] = mapped_column(String(255))
    model_version: Mapped[str | None] = mapped_column(String(255))
    config_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    deterministic_result: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    jev_signals: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    jev_reasons: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship("Job")
