"""Once-a-day Telegram digest of second-tier opportunities.

Strong opportunities alert immediately (see ``notifications``). Everything
that is still worth a glance but did not earn an alert — a REVIEW below the
alert threshold, an on-site role, a city with no stated work mode, a good job
first seen too late to alert — is listed once in a compact evening digest so
it is not invisible without a UI. Each job appears in at most one digest.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import HumanReviewStatus, OpportunityNotification
from ai_job_hunter.services.notifications import (
    COVER_LETTER_CALLBACK_PREFIX,
    FEEDBACK_DISMISS_PREFIX,
    FEEDBACK_SAVE_PREFIX,
    TELEGRAM_CHANNEL,
    NotificationProvider,
    _clean_label,
    _current_opportunities,
    _html,
    _job_identity,
    _older_than,
    _safe_public_url,
    _sent_job_identities,
    _WORK_MODE_LABELS,
)
from ai_job_hunter.services.opportunities import Opportunity

DIGEST_CHANNEL = "TELEGRAM_DIGEST"
DIGEST_MIN_PRIORITY = 50
# On-site roles below the alert bar only make the digest when clearly good.
DIGEST_ONSITE_MIN_PRIORITY = 70
DIGEST_MAX_ITEMS = 12
DIGEST_MAX_AGE_DAYS = 7
DIGEST_MIN_INTERVAL = timedelta(hours=20)
# Suppression reasons that mean "worth a look, but not an alert". Jobs held
# back by the per-company cap or still pending alert later, so they are left out.
_DIGEST_REASONS = {
    "review_priority_below_threshold",
    "onsite_not_exceptional",
    "uncertain_location",
    "older_than_max_age",
}


@dataclass(frozen=True, slots=True)
class DigestEntry:
    item: Opportunity
    notification_fingerprint: str
    reason: str


@dataclass(frozen=True, slots=True)
class DigestResult:
    status: str  # "sent", "empty", "too_soon", "failed"
    entries: tuple[DigestEntry, ...] = ()
    message: str | None = None


def select_digest_entries(
    session: Session,
    candidate: CandidateConfig,
    *,
    review_threshold: int,
    max_age_days: int | None,
    limit: int = DIGEST_MAX_ITEMS,
) -> list[DigestEntry]:
    current = _current_opportunities(session, candidate, review_threshold, max_age_days=max_age_days)
    candidates = [row for row in current if not row.eligible and row.suppression_reason in _DIGEST_REASONS]
    if not candidates:
        return []
    job_ids = {row.item.job_id for row in candidates}
    already_listed = _jobs_with_rows(session, job_ids)
    sent_identities = _sent_job_identities(session)
    seen: set[tuple[str, frozenset[str], frozenset[str]]] = set()
    entries: list[DigestEntry] = []
    for row in sorted(candidates, key=lambda r: -(r.item.priority or 0)):
        item = row.item
        decision = item.decision.value if item.decision is not None else None
        if decision not in {FinalDecision.APPLY.value, FinalDecision.REVIEW.value}:
            continue
        if item.application_status is not None or item.review_state is HumanReviewStatus.DISMISSED:
            continue
        if item.job_id in already_listed or _older_than(item, DIGEST_MAX_AGE_DAYS):
            continue
        priority = item.priority or 0
        if decision == FinalDecision.REVIEW.value and priority < DIGEST_MIN_PRIORITY:
            continue
        if item.remote_policy == "ONSITE" and priority < DIGEST_ONSITE_MIN_PRIORITY:
            continue
        identity = _job_identity(item)
        if identity in seen or (identity in sent_identities and item.job_id not in sent_identities[identity]):
            continue
        seen.add(identity)
        entries.append(DigestEntry(item, row.notification_fingerprint, row.suppression_reason or ""))
        if len(entries) >= limit:
            break
    return entries


def send_digest(
    session: Session,
    candidate: CandidateConfig,
    provider: NotificationProvider,
    *,
    review_threshold: int,
    max_age_days: int | None,
    now: datetime | None = None,
    force: bool = False,
) -> DigestResult:
    """Send at most one digest per ~day; record its jobs so they never repeat."""

    now = now or datetime.now(UTC)
    if not force:
        last = session.scalar(
            select(func.max(OpportunityNotification.sent_at)).where(
                OpportunityNotification.channel == DIGEST_CHANNEL
            )
        )
        if last is not None and now - _aware(last) < DIGEST_MIN_INTERVAL:
            return DigestResult("too_soon")
    entries = select_digest_entries(
        session, candidate, review_threshold=review_threshold, max_age_days=max_age_days
    )
    if not entries:
        return DigestResult("empty")
    message = format_digest_message(entries)
    try:
        sent = provider.send_message(message, reply_markup=digest_keyboard(entries))
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing
        session.rollback()
        return DigestResult("failed", tuple(entries), message)
    for entry in entries:
        session.add(
            OpportunityNotification(
                job_id=entry.item.job_id,
                evaluation_fingerprint=entry.notification_fingerprint,
                channel=DIGEST_CHANNEL,
                decision=entry.item.decision.value,
                priority=entry.item.priority,
                status="SENT",
                message=_clean_label(f"{entry.item.title} — {entry.item.company}", 400),
                attempt_count=1,
                suppression_reason=entry.reason,
                provider_message_id=sent.message_id,
                sent_at=now,
            )
        )
    session.commit()
    return DigestResult("sent", tuple(entries), message)


def preview_digest(
    session: Session,
    candidate: CandidateConfig,
    *,
    review_threshold: int,
    max_age_days: int | None,
) -> DigestResult:
    entries = select_digest_entries(
        session, candidate, review_threshold=review_threshold, max_age_days=max_age_days
    )
    if not entries:
        return DigestResult("empty")
    return DigestResult("preview", tuple(entries), format_digest_message(entries))


# The work mode is already on the line, so on-site needs no extra tag.
_REASON_TAGS = {
    "uncertain_location": "⚠️ puede no ser remota",
    "older_than_max_age": "publicada hace días",
}


def format_digest_message(entries: list[DigestEntry]) -> str:
    count = len(entries)
    lines = [
        f"🗞️ <b>Resumen del día</b> · {count} oferta{'s' if count != 1 else ''} de segunda fila",
        "<i>No llegaron como alerta. Usa los botones con el número de la oferta.</i>",
    ]
    for index, entry in enumerate(entries, start=1):
        item = entry.item
        url = _safe_public_url(item.url)
        title = _html(item.title, 110)
        if url:
            title = f'<a href="{html.escape(url, quote=True)}">{title}</a>'
        priority = item.priority if item.priority is not None else "?"
        details = [
            _html(item.location, 60) if item.location else "ubicación no indicada",
            _WORK_MODE_LABELS.get(item.remote_policy or "", "modalidad no indicada"),
        ]
        tag = _REASON_TAGS.get(entry.reason)
        if tag:
            details.append(tag)
        lines.extend(
            [
                "",
                f"<b>{index}.</b> [{priority}] {title}",
                f"🏢 {_html(item.company, 80)} · " + " · ".join(details),
            ]
        )
    if any((_host(entry.item.url) or "").endswith("himalayas.app") for entry in entries):
        lines.extend(["", '📡 Algunas vía <a href="https://himalayas.app">Himalayas</a>'])
    lines.append("<i>[n] = prioridad de revisión, no probabilidad.</i>")
    return "\n".join(lines)


def digest_keyboard(entries: list[DigestEntry]) -> dict[str, Any]:
    """One row per job: cover letter, 👍, 👎 — labelled with its number."""

    rows = []
    for index, entry in enumerate(entries, start=1):
        job_id = entry.item.job_id
        rows.append(
            [
                {"text": f"{index} ✍️", "callback_data": f"{COVER_LETTER_CALLBACK_PREFIX}{job_id}"},
                {"text": f"{index} 👍", "callback_data": f"{FEEDBACK_SAVE_PREFIX}{job_id}"},
                {"text": f"{index} 👎", "callback_data": f"{FEEDBACK_DISMISS_PREFIX}{job_id}"},
            ]
        )
    return {"inline_keyboard": rows}


def _host(url: str | None) -> str | None:
    safe = _safe_public_url(url)
    return urlsplit(safe).hostname if safe else None


def _jobs_with_rows(session: Session, job_ids: set[UUID]) -> set[UUID]:
    """Jobs already listed in a digest or already alerted."""

    ids = list(job_ids)
    found: set[UUID] = set()
    for offset in range(0, len(ids), 400):
        found.update(
            session.scalars(
                select(OpportunityNotification.job_id).where(
                    OpportunityNotification.job_id.in_(ids[offset : offset + 400]),
                    OpportunityNotification.status == "SENT",
                    OpportunityNotification.channel.in_((DIGEST_CHANNEL, TELEGRAM_CHANNEL)),
                )
            ).all()
        )
    return found


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
