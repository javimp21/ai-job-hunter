"""Quotas for what costs money per use (letters, interview briefs, the weekly opinion review).

Every use is a row in ``usage_events`` of the acting person; a limit counts those rows in a window. The owner is not
limited. Asking again for something already written never reaches this module: it is resent from the stored document.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_job_hunter.models.usage import UsageEvent

LETTER = "LETTER"
INTERVIEW = "INTERVIEW"
REVIEW = "REVIEW"

# kind -> ((window, most uses in it, how the window is named in the message), ...)
LIMITS: dict[str, tuple[tuple[timedelta, int, str], ...]] = {
    LETTER: ((timedelta(days=1), 3, "hoy"), (timedelta(days=7), 10, "esta semana")),
    INTERVIEW: ((timedelta(days=1), 3, "hoy"), (timedelta(days=7), 10, "esta semana")),
    REVIEW: ((timedelta(days=6), 1, "esta semana"),),
}
LABELS = {LETTER: "cartas", INTERVIEW: "preparaciones de entrevista", REVIEW: "revisiones"}


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    allowed: bool
    message: str | None = None


def check_quota(session: Session, kind: str, *, now: datetime | None = None) -> QuotaDecision:
    """Whether the acting person may use ``kind`` now (reads are scoped to them by the user context)."""

    moment = now or datetime.now(UTC)
    for window, most, name in LIMITS[kind]:
        used = session.scalar(
            select(func.count()).select_from(UsageEvent).where(UsageEvent.kind == kind, UsageEvent.used_at > moment - window)
        ) or 0
        if used >= most:
            return QuotaDecision(
                False, f"Ya has usado tus {most} {LABELS[kind]} de {name}. Vuelve a probar más adelante."
            )
    return QuotaDecision(True)


def record_usage(session: Session, kind: str, job_id: UUID | None = None, *, now: datetime | None = None) -> None:
    session.add(UsageEvent(kind=kind, job_id=job_id, used_at=now or datetime.now(UTC)))
    session.flush()
