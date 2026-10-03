"""Idempotent opportunity notification delivery with a safe Telegram adapter."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.candidates.experience import ExperienceOutcome
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import (
    HumanReviewStatus,
    Job,
    JobEvaluation,
    OpportunityNotification,
    OpportunityNotificationStatus,
)
from ai_job_hunter.services.opportunities import Opportunity, list_opportunities


TELEGRAM_CHANNEL = "TELEGRAM"
_REASON_LABELS = {
    "EXPERIENCE_BORDERLINE": "experiencia algo justa",
    "EXPERIENCE_UNKNOWN": "experiencia requerida no verificada",
    "ROLE_FAMILY_UNCERTAIN": "encaje de rol/backend por confirmar",
    "STACK_UNCERTAIN": "encaje de stack por confirmar",
    "COMPENSATION_UNKNOWN": "salario no publicado",
    "SENIORITY_UNCERTAIN": "seniority no clara",
    "INSUFFICIENT_DESCRIPTION": "descripción escasa",
    "LOCATION_UNCERTAIN": "elegibilidad geográfica por confirmar",
    "OTHER": "revisar la información disponible",
}
_WHITESPACE = re.compile(r"\s+")


class NotificationProvider(Protocol):
    """Minimal provider contract so notification delivery can be faked offline."""

    def send_message(
        self, message: str, *, reply_markup: dict[str, Any] | None = None
    ) -> "TelegramSendResult":
        """Send one message or raise a safe provider exception."""


COVER_LETTER_CALLBACK_PREFIX = "cl:"


def cover_letter_keyboard(job_id: UUID) -> dict[str, Any]:
    """Inline button that asks the bot for a cover-letter draft (callback <= 64 bytes)."""

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✍️ Generar cover letter",
                    "callback_data": f"{COVER_LETTER_CALLBACK_PREFIX}{job_id}",
                }
            ]
        ]
    }


class TelegramRejectedError(RuntimeError):
    """Telegram returned a definitive 4xx rejection; a later retry may succeed."""

    def __init__(self, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("Telegram rejected the message.")


class TelegramAmbiguousError(RuntimeError):
    """Delivery may have happened, so retrying could create a duplicate."""

    def __init__(self) -> None:
        super().__init__("Telegram delivery outcome is unknown.")


@dataclass(frozen=True, slots=True)
class TelegramSendResult:
    """Safe subset of Telegram's success response."""

    message_id: str | None = None


class TelegramProvider:
    """Small Telegram Bot API client that never surfaces its credential-bearing URL."""

    def __init__(
        self,
        bot_token: SecretStr | str,
        chat_id: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        token = bot_token.get_secret_value() if isinstance(bot_token, SecretStr) else bot_token
        if not isinstance(token, str) or not token.strip() or not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError("Telegram notification configuration is incomplete.")
        self._bot_token = token.strip()
        self._chat_id = chat_id.strip()
        self._client = client
        self._timeout = timeout

    def send_message(
        self, message: str, *, reply_markup: dict[str, Any] | None = None
    ) -> TelegramSendResult:
        client = self._client or httpx.Client()
        should_close = self._client is None
        endpoint = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        data = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if reply_markup is not None:
            data["reply_markup"] = json.dumps(reply_markup, separators=(",", ":"))
        try:
            response = client.post(endpoint, data=data, timeout=self._timeout)
        except httpx.HTTPError:
            # Never chain/format the httpx exception: it may contain the token URL.
            raise TelegramAmbiguousError() from None
        finally:
            if should_close:
                client.close()

        if 400 <= response.status_code < 500:
            raise TelegramRejectedError(response.status_code)
        if response.status_code >= 500 or response.status_code < 200:
            raise TelegramAmbiguousError()
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            raise TelegramAmbiguousError() from None
        if isinstance(body, dict) and body.get("ok") is True:
            result = body.get("result")
            message_id = result.get("message_id") if isinstance(result, dict) else None
            return TelegramSendResult(
                message_id=str(message_id)
                if isinstance(message_id, (str, int))
                else None
            )
        if isinstance(body, dict) and body.get("ok") is False:
            error_code = body.get("error_code")
            if isinstance(error_code, int) and 400 <= error_code < 500:
                raise TelegramRejectedError(error_code)
        raise TelegramAmbiguousError()


@dataclass(frozen=True, slots=True)
class NotificationPreview:
    """A selected, safe message preview; it contains no candidate facts."""

    job_id: UUID
    evaluation_fingerprint: str
    decision: str
    company: str
    title: str
    location: str | None
    priority: int | None
    message: str


@dataclass(frozen=True, slots=True)
class NotificationItemResult:
    job_id: UUID
    company: str
    title: str
    status: str
    failure_reason: str | None = None


@dataclass(slots=True)
class NotificationBatchResult:
    created: int = 0
    sent: int = 0
    failed: int = 0
    suppressed: int = 0
    reused: int = 0
    items: list[NotificationItemResult] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _CurrentOpportunity:
    item: Opportunity
    notification_fingerprint: str
    preview: NotificationPreview
    eligible: bool
    suppression_reason: str | None


def preview_notifications(
    session: Session,
    candidate: CandidateConfig,
    *,
    review_threshold: int = 70,
    limit: int | None = None,
) -> list[NotificationPreview]:
    """Return qualifying APPLY/high-priority REVIEW messages without writes."""

    _validate_threshold(review_threshold)
    current = _current_opportunities(session, candidate, review_threshold)
    return _preview_current(session, current, limit=limit)


def _preview_current(
    session: Session,
    current: list[_CurrentOpportunity],
    *,
    limit: int | None,
) -> list[NotificationPreview]:
    eligible = [row for row in current if row.eligible]
    existing_rows = _notification_rows_for(session, eligible)
    sendable = [
        row.preview
        for row in eligible
        if _would_send(row, existing_rows.get((row.preview.job_id, row.notification_fingerprint)))
    ]
    if limit is not None:
        if limit < 1:
            raise ValueError("notification limit must be positive")
        sendable = sendable[:limit]
    return sendable


def send_notifications(
    session: Session,
    candidate: CandidateConfig,
    provider: NotificationProvider,
    *,
    review_threshold: int = 70,
    limit: int | None = None,
) -> NotificationBatchResult:
    """Record selected evaluations and send pending notifications once."""

    _validate_threshold(review_threshold)
    current = _current_opportunities(session, candidate, review_threshold)
    sendable = _preview_current(session, current, limit=limit)
    selected_keys = {(item.job_id, item.evaluation_fingerprint) for item in sendable}
    result = _materialize(session, current, selected_keys=selected_keys)
    session.commit()
    _suppress_outdated_pending(
        session,
        {(row.item.job_id, row.notification_fingerprint) for row in current},
    )
    session.commit()
    _recover_interrupted_dispatches(session)
    session.commit()
    pending_ids = {
        row.id
        for row in session.scalars(
            select(OpportunityNotification).where(
                OpportunityNotification.status == OpportunityNotificationStatus.PENDING.value
            )
        ).all()
        if (row.job_id, row.evaluation_fingerprint) in selected_keys
    }
    _dispatch_pending(session, provider, result, limit=limit, only_ids=pending_ids)
    return result


def list_pending_notifications(
    session: Session, *, limit: int = 50
) -> list[OpportunityNotification]:
    """List messages that have not begun a delivery attempt."""

    if limit < 1:
        raise ValueError("notification limit must be positive")
    return list(
        session.scalars(
            select(OpportunityNotification)
            .options(joinedload(OpportunityNotification.job))
            .where(
                OpportunityNotification.status == OpportunityNotificationStatus.PENDING.value,
                OpportunityNotification.dispatch_started.is_(False),
                (OpportunityNotification.attempt_count == 0)
                | (OpportunityNotification.retryable.is_(True)),
            )
            .order_by(OpportunityNotification.created_at, OpportunityNotification.id)
            .limit(limit)
        ).all()
    )


def list_notification_history(
    session: Session, *, limit: int = 50
) -> list[OpportunityNotification]:
    """List recent notification ledger rows without exposing credentials."""

    if limit < 1:
        raise ValueError("notification limit must be positive")
    return list(
        session.scalars(
            select(OpportunityNotification)
            .options(joinedload(OpportunityNotification.job))
            .order_by(OpportunityNotification.created_at.desc(), OpportunityNotification.id.desc())
            .limit(limit)
        ).all()
    )


def retry_failed_notifications(
    session: Session,
    candidate: CandidateConfig,
    provider: NotificationProvider,
    *,
    review_threshold: int = 70,
    limit: int | None = None,
) -> NotificationBatchResult:
    """Retry safe provider rejections and interrupted retries that meet policy."""

    _validate_threshold(review_threshold)
    if limit is not None and limit < 1:
        raise ValueError("notification limit must be positive")
    current = _current_opportunities(session, candidate, review_threshold)
    by_fingerprint = {
        (row.item.job_id, row.notification_fingerprint): row for row in current
    }
    result = NotificationBatchResult()
    rows = list(
        session.scalars(
            select(OpportunityNotification)
            .where(
                OpportunityNotification.status.in_(
                    (
                        OpportunityNotificationStatus.FAILED.value,
                        OpportunityNotificationStatus.PENDING.value,
                    )
                ),
                OpportunityNotification.retryable.is_(True),
                OpportunityNotification.dispatch_started.is_(False),
            )
            .order_by(OpportunityNotification.created_at, OpportunityNotification.id)
        ).all()
    )
    retry_rows: list[OpportunityNotification] = []
    for row in rows:
        current_item = by_fingerprint.get((row.job_id, row.evaluation_fingerprint))
        if current_item is None or not current_item.eligible:
            continue
        row.status = OpportunityNotificationStatus.PENDING.value
        row.message = current_item.preview.message
        row.decision = current_item.preview.decision
        row.priority = current_item.preview.priority
        row.failure_reason = None
        retry_rows.append(row)
        if limit is not None and len(retry_rows) >= limit:
            break
    session.commit()
    _recover_interrupted_dispatches(session)
    session.commit()
    _dispatch_pending(session, provider, result, limit=limit, only_ids={row.id for row in retry_rows})
    return result


class NotificationService:
    """Object facade for CLI and orchestration use."""

    def __init__(
        self,
        session: Session,
        provider: NotificationProvider | None,
        candidate: CandidateConfig,
        *,
        review_threshold: int = 70,
    ) -> None:
        _validate_threshold(review_threshold)
        self.session = session
        self.provider = provider
        self.candidate = candidate
        self.review_threshold = review_threshold

    def preview(self, *, limit: int | None = None) -> list[NotificationPreview]:
        return preview_notifications(
            self.session,
            self.candidate,
            review_threshold=self.review_threshold,
            limit=limit,
        )

    def send_pending(self, *, limit: int | None = None) -> NotificationBatchResult:
        if self.provider is None:
            raise ValueError("A notification provider is required to send messages.")
        return send_notifications(
            self.session,
            self.candidate,
            self.provider,
            review_threshold=self.review_threshold,
            limit=limit,
        )

    def retry_failed(self, *, limit: int | None = None) -> NotificationBatchResult:
        if self.provider is None:
            raise ValueError("A notification provider is required to send messages.")
        return retry_failed_notifications(
            self.session,
            self.candidate,
            self.provider,
            review_threshold=self.review_threshold,
            limit=limit,
        )


def _current_opportunities(
    session: Session,
    candidate: CandidateConfig,
    threshold: int,
) -> list[_CurrentOpportunity]:
    opportunities = list_opportunities(
        session,
        candidate,
        limit=100_000,
        include_applied=True,
        include_skip=True,
        include_dismissed=True,
    )
    current_rows = [
        item
        for item in opportunities
        if item.decision is not None
        and item.evaluation_fingerprint is not None
        and not item.evaluation_is_stale
    ]
    if not current_rows:
        return []
    evaluations: list[JobEvaluation] = []
    for offset in range(0, len(current_rows), 400):
        batch = current_rows[offset : offset + 400]
        evaluations.extend(
            session.scalars(
                select(JobEvaluation).where(
                    JobEvaluation.job_id.in_({item.job_id for item in batch}),
                    JobEvaluation.evaluation_fingerprint.in_(
                        {
                            item.evaluation_fingerprint
                            for item in batch
                            if item.evaluation_fingerprint
                        }
                    ),
                    JobEvaluation.status == "EVALUATED",
                )
            ).all()
        )
    evaluations_by_key = {
        (row.job_id, row.evaluation_fingerprint): row for row in evaluations
    }
    sent_decisions = _sent_decisions_by_job(session, {item.job_id for item in current_rows})
    result: list[_CurrentOpportunity] = []
    for item in current_rows:
        evaluation = evaluations_by_key.get((item.job_id, item.evaluation_fingerprint))
        if evaluation is None:
            continue
        fingerprint = _notification_fingerprint(evaluation)
        decision = item.decision.value
        eligible = decision == FinalDecision.APPLY.value or (
            decision == FinalDecision.REVIEW.value
            and item.priority is not None
            and item.priority >= threshold
        )
        reason = None if eligible else "review_priority_below_threshold"
        if eligible:
            reason = _human_state_suppression(item) or _repeat_suppression(
                decision, sent_decisions.get(item.job_id, {}), fingerprint
            )
            eligible = reason is None
        preview = NotificationPreview(
            job_id=item.job_id,
            evaluation_fingerprint=fingerprint,
            decision=decision,
            company=_clean_label(item.company, 160),
            title=_clean_label(item.title, 200),
            location=_clean_label(item.location, 120) if item.location else None,
            priority=item.priority,
            message=format_notification_message(item),
        )
        result.append(_CurrentOpportunity(item, fingerprint, preview, eligible, reason))
    result.sort(
        key=lambda row: (
            0 if row.eligible else 1,
            -(row.preview.priority if row.preview.priority is not None else -1),
            row.preview.company.casefold(),
            row.preview.title.casefold(),
        )
    )
    return result


def _human_state_suppression(item: Opportunity) -> str | None:
    """The user already acted on this job; an alert would only be noise."""

    if item.application_status is not None:
        return "already_applied"
    if item.review_state is HumanReviewStatus.DISMISSED:
        return "dismissed"
    return None


def _repeat_suppression(
    decision: str,
    sent: dict[str, str],
    fingerprint: str,
) -> str | None:
    """Alert once per job; only a REVIEW -> APPLY upgrade justifies a new alert.

    ``sent`` maps notification fingerprints already delivered for this job to
    their decision. Re-evaluations (new description, new prefilter version)
    produce new fingerprints but are not news by themselves.
    """

    previous = {value for key, value in sent.items() if key != fingerprint}
    if not previous:
        return None
    if decision == FinalDecision.APPLY.value and FinalDecision.APPLY.value not in previous:
        return None
    return "already_notified"


def _sent_decisions_by_job(session: Session, job_ids: set[UUID]) -> dict[UUID, dict[str, str]]:
    result: dict[UUID, dict[str, str]] = {}
    ids = list(job_ids)
    for offset in range(0, len(ids), 400):
        for row in session.scalars(
            select(OpportunityNotification).where(
                OpportunityNotification.job_id.in_(ids[offset : offset + 400]),
                OpportunityNotification.channel == TELEGRAM_CHANNEL,
                OpportunityNotification.status == OpportunityNotificationStatus.SENT.value,
            )
        ).all():
            result.setdefault(row.job_id, {})[row.evaluation_fingerprint] = row.decision
    return result


def _materialize(
    session: Session,
    current: list[_CurrentOpportunity],
    *,
    selected_keys: set[tuple[UUID, str]],
) -> NotificationBatchResult:
    result = NotificationBatchResult()
    for item in current:
        selected = (item.preview.job_id, item.notification_fingerprint) in selected_keys
        if not item.eligible and item.preview.decision not in {
            FinalDecision.REVIEW.value,
            FinalDecision.SKIP.value,
        }:
            continue
        existing = session.scalar(
            select(OpportunityNotification).where(
                OpportunityNotification.job_id == item.preview.job_id,
                OpportunityNotification.evaluation_fingerprint == item.notification_fingerprint,
                OpportunityNotification.channel == TELEGRAM_CHANNEL,
            )
        )
        if item.eligible and not selected:
            if existing is not None:
                result.reused += 1
            continue
        if existing is None:
            if not item.eligible and item.preview.decision == FinalDecision.SKIP.value:
                continue
            status = (
                OpportunityNotificationStatus.PENDING.value
                if item.eligible
                else OpportunityNotificationStatus.SUPPRESSED.value
            )
            row = OpportunityNotification(
                job_id=item.preview.job_id,
                evaluation_fingerprint=item.notification_fingerprint,
                channel=TELEGRAM_CHANNEL,
                decision=item.preview.decision,
                priority=item.preview.priority,
                status=status,
                message=item.preview.message,
                suppression_reason=item.suppression_reason,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
                if item.eligible:
                    result.created += 1
                else:
                    result.suppressed += 1
            except IntegrityError:
                result.reused += 1
            continue

        result.reused += 1
        if existing.status == OpportunityNotificationStatus.SUPPRESSED.value:
            if item.eligible and (existing.attempt_count == 0 or existing.retryable):
                existing.status = OpportunityNotificationStatus.PENDING.value
                existing.suppression_reason = None
                existing.message = item.preview.message
                existing.decision = item.preview.decision
                existing.priority = item.preview.priority
                result.created += 1
            elif not item.eligible:
                existing.suppression_reason = (
                    item.suppression_reason or "decision_not_notifiable"
                )
        elif existing.status == OpportunityNotificationStatus.PENDING.value:
            if item.eligible:
                existing.message = item.preview.message
                existing.decision = item.preview.decision
                existing.priority = item.preview.priority
            elif not existing.dispatch_started:
                existing.status = OpportunityNotificationStatus.SUPPRESSED.value
                existing.suppression_reason = (
                    item.suppression_reason or "decision_not_notifiable"
                )
                result.suppressed += 1
        elif existing.status in {
            OpportunityNotificationStatus.SENT.value,
            OpportunityNotificationStatus.FAILED.value,
        }:
            continue
    return result


def _notification_rows_for(
    session: Session,
    opportunities: list[_CurrentOpportunity],
) -> dict[tuple[UUID, str], OpportunityNotification]:
    if not opportunities:
        return {}
    rows: list[OpportunityNotification] = []
    for offset in range(0, len(opportunities), 400):
        batch = opportunities[offset : offset + 400]
        rows.extend(
            session.scalars(
                select(OpportunityNotification).where(
                    OpportunityNotification.job_id.in_(
                        {item.preview.job_id for item in batch}
                    ),
                    OpportunityNotification.evaluation_fingerprint.in_(
                        {item.notification_fingerprint for item in batch}
                    ),
                    OpportunityNotification.channel == TELEGRAM_CHANNEL,
                )
            ).all()
        )
    return {(row.job_id, row.evaluation_fingerprint): row for row in rows}


def _would_send(
    current: _CurrentOpportunity,
    existing: OpportunityNotification | None,
) -> bool:
    if not current.eligible:
        return False
    if existing is None:
        return True
    if existing.status == OpportunityNotificationStatus.PENDING.value:
        return not existing.dispatch_started and (
            existing.attempt_count == 0 or existing.retryable
        )
    if existing.status == OpportunityNotificationStatus.SUPPRESSED.value:
        return existing.attempt_count == 0 or existing.retryable
    # SENT and every FAILED record require no further automatic delivery.
    return False


def _suppress_outdated_pending(
    session: Session,
    current_fingerprints: set[tuple[UUID, str]],
) -> None:
    pending = session.scalars(
        select(OpportunityNotification).where(
            OpportunityNotification.status == OpportunityNotificationStatus.PENDING.value,
            OpportunityNotification.dispatch_started.is_(False),
        )
    ).all()
    for row in pending:
        if (row.job_id, row.evaluation_fingerprint) not in current_fingerprints:
            row.status = OpportunityNotificationStatus.SUPPRESSED.value
            row.suppression_reason = "evaluation_no_longer_current"


def _dispatch_pending(
    session: Session,
    provider: NotificationProvider,
    result: NotificationBatchResult,
    *,
    limit: int | None,
    only_ids: set[UUID] | None = None,
) -> None:
    statement = select(OpportunityNotification).where(
        OpportunityNotification.status == OpportunityNotificationStatus.PENDING.value,
        OpportunityNotification.dispatch_started.is_(False),
        (OpportunityNotification.attempt_count == 0)
        | (OpportunityNotification.retryable.is_(True)),
    )
    if only_ids is not None:
        if not only_ids:
            return
        statement = statement.where(OpportunityNotification.id.in_(only_ids))
    statement = statement.order_by(
        OpportunityNotification.priority.desc().nullslast(),
        OpportunityNotification.created_at,
        OpportunityNotification.id,
    )
    if limit is not None:
        statement = statement.limit(limit)
    ids = list(session.scalars(statement.with_only_columns(OpportunityNotification.id)).all())
    for notification_id in ids:
        row = session.get(OpportunityNotification, notification_id)
        if row is None or row.status != OpportunityNotificationStatus.PENDING.value:
            continue
        claim = session.execute(
            update(OpportunityNotification)
            .where(
                OpportunityNotification.id == notification_id,
                OpportunityNotification.status == OpportunityNotificationStatus.PENDING.value,
                OpportunityNotification.dispatch_started.is_(False),
                (OpportunityNotification.attempt_count == 0) | (OpportunityNotification.retryable.is_(True)),
            )
            .values(
                attempt_count=OpportunityNotification.attempt_count + 1,
                dispatch_started=True,
                dispatch_started_at=datetime.now(UTC),
                retryable=False,
            )
        )
        session.commit()
        if claim.rowcount != 1:
            continue
        row = session.get(OpportunityNotification, notification_id)
        if row is None:
            continue
        try:
            delivery = provider.send_message(
                row.message, reply_markup=cover_letter_keyboard(row.job_id)
            )
            row.provider_message_id = (
                delivery.message_id
                if isinstance(delivery, TelegramSendResult)
                else None
            )
        except TelegramRejectedError as error:
            status_code = error.status_code
            row.status = OpportunityNotificationStatus.FAILED.value
            row.failure_reason = f"telegram_rejected_{status_code}" if status_code is not None else "telegram_rejected"
            row.retryable = True
            row.dispatch_started = False
            row.dispatch_started_at = None
            result.failed += 1
        except Exception:
            # Do not expose provider exception text; transports can include secrets.
            row.status = OpportunityNotificationStatus.FAILED.value
            row.failure_reason = "delivery_outcome_unknown"
            row.retryable = False
            row.dispatch_started = False
            row.dispatch_started_at = None
            result.failed += 1
        else:
            row.status = OpportunityNotificationStatus.SENT.value
            row.failure_reason = None
            row.retryable = False
            row.dispatch_started = False
            row.dispatch_started_at = None
            row.sent_at = datetime.now(UTC)
            result.sent += 1
        result.items.append(_item_result(session, row))
        session.commit()


def format_notification_message(item: Opportunity) -> str:
    """Build a Telegram HTML message from public job fields and fixed labels.

    Every dynamic value is length-bounded and HTML-escaped; raw Jev text and
    candidate facts (years, personal gaps) are never included.
    """

    decision = item.decision.value if item.decision is not None else "REVIEW"
    icon = "🔥" if decision == FinalDecision.APPLY.value else "👀"
    header = f"{icon} <b>{decision}</b>"
    if item.priority is not None:
        header += f" · prioridad {item.priority}/100"
    lines = [
        header,
        f"<b>{_html(item.title, 200)}</b>",
        f"🏢 {_html(item.company, 160)}",
        "",
        f"📍 {_html(item.location, 120) if item.location else 'Ubicación no indicada'}"
        f" · {_WORK_MODE_LABELS.get(item.remote_policy or '', 'modalidad no indicada')}",
        f"💰 {_format_salary(item) or 'Salario no publicado'}",
        f"🎓 {_format_experience(item)}",
    ]
    technologies = list(dict.fromkeys((*item.required_technologies, *item.technologies)))
    if technologies:
        lines.append("🧰 " + ", ".join(_html(technology, 45) for technology in technologies[:6]))
    warning = _location_warning(item)
    if warning:
        lines.extend(["", warning])
    strengths = _strengths(item.jev_signals)
    concerns = _safe_reasons(item.jev_reasons, decision)
    if strengths or concerns:
        lines.append("")
    if strengths:
        lines.append("✅ <b>Encaja en:</b> " + ", ".join(strengths))
    if concerns and decision != FinalDecision.APPLY.value:
        lines.append("❓ <b>A revisar:</b> " + "; ".join(concerns[:3]))
    url = _safe_public_url(item.url)
    if url:
        lines.extend(["", f'<a href="{html.escape(url, quote=True)}">Ver oferta →</a>'])
    lines.append("<i>La prioridad ordena la revisión; no es una probabilidad.</i>")
    return "\n".join(lines)


_WORK_MODE_LABELS = {"REMOTE": "🏠 remoto", "HYBRID": "🏙️ híbrido", "ONSITE": "🏢 presencial"}
_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}
_PERIOD_LABELS = {"YEAR": "/año", "MONTH": "/mes", "WEEK": "/semana", "DAY": "/día", "HOUR": "/hora"}
_SIGNAL_LABELS = {
    "role_relevance": "rol",
    "backend_relevance": "backend",
    "stack_transferability": "stack",
    "experience_accessibility": "experiencia accesible",
    "requirements_flexibility": "requisitos flexibles",
    "career_value": "valor de carrera",
    "observable_role_quality": "calidad de la oferta",
}
_REMOTE_TEXT = re.compile(r"\b(?:remote|remoto|remota|anywhere|worldwide|teletrabajo)\b", re.IGNORECASE)


def _html(value: str | None, limit: int) -> str:
    return html.escape(_clean_label(value, limit), quote=False)


def _format_salary(item: Opportunity) -> str | None:
    if item.salary_min is None and item.salary_max is None:
        return None
    currency = (item.currency or "").upper()
    symbol = _CURRENCY_SYMBOLS.get(currency, _clean_label(currency, 8))
    low = _format_amount(item.salary_min)
    high = _format_amount(item.salary_max)
    if low and high:
        amount = low if low == high else f"{low}–{high}"
    elif low:
        amount = f"desde {low}"
    else:
        amount = f"hasta {high}"
    period = _PERIOD_LABELS.get((item.salary_period or "").upper(), "")
    return html.escape(" ".join(part for part in (amount, symbol) if part) + period, quote=False)[:100]


def _format_amount(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return _clean_label(str(value), 20)
    if number != number.to_integral_value():
        return _clean_label(str(value), 20)
    return f"{int(number):,}".replace(",", ".")


def _format_experience(item: Opportunity) -> str:
    experience = item.experience
    if experience is None or not experience.mandatory:
        return "Experiencia: no especificada"
    labels = {
        ExperienceOutcome.MEETS: "encaja",
        ExperienceOutcome.STRETCH: "⚠️ stretch (piden más experiencia)",
        ExperienceOutcome.INCOMPATIBLE: "fuera de rango",
        ExperienceOutcome.UNKNOWN: "encaje no claro",
    }
    requirement = "; ".join(item.display() for item in experience.mandatory)
    for english, spanish in _EXPERIENCE_WORDS:
        requirement = requirement.replace(english, spanish)
    return f"Experiencia: piden {_html(requirement, 200)} — {labels[experience.outcome]}"


_EXPERIENCE_WORDS = (
    ("minimum ", ""),
    ("less than ", "menos de "),
    ("up to ", "hasta "),
    ("years", "años"),
    ("year", "año"),
    (" to ", " a "),
)


def _location_warning(item: Opportunity) -> str | None:
    """Flag a named city with no stated work mode outside the configured locations."""

    if item.remote_policy is not None or not item.location or _REMOTE_TEXT.search(item.location):
        return None
    signals = item.deterministic_result.get("signals") if isinstance(item.deterministic_result, dict) else None
    preferred = signals.get("preferred_location") if isinstance(signals, dict) else None
    if isinstance(preferred, dict) and preferred.get("status") == "COMPATIBLE":
        return None
    return (
        f"⚠️ {_html(item.location, 80)}: la oferta no indica modalidad; "
        "puede ser presencial o híbrida fuera de tus ubicaciones."
    )


def _strengths(signals: Any) -> list[str]:
    if not isinstance(signals, dict):
        return []
    strong: list[tuple[float, str]] = []
    for key, label in _SIGNAL_LABELS.items():
        signal = signals.get(key)
        value = signal.get("value") if isinstance(signal, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0.75:
            strong.append((value, label))
    return [label for _, label in sorted(strong, key=lambda pair: -pair[0])[:4]]


def _safe_reasons(raw: Any, decision: str) -> list[str]:
    if decision == FinalDecision.APPLY.value:
        return ["encaje fuerte de rol, backend y experiencia"]
    records = raw.get("review_reasons", []) if isinstance(raw, dict) else []
    labels: list[str] = []
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            code = record.get("code")
            if isinstance(code, dict):
                code = code.get("value")
            label = _REASON_LABELS.get(str(code).upper()) if code is not None else None
            if label and label not in labels:
                labels.append(label)
            if len(labels) == 3:
                break
    return labels or ["revisar la información disponible"]


def _notification_fingerprint(evaluation: JobEvaluation) -> str:
    payload = {
        "job_id": str(evaluation.job_id),
        "evaluation_fingerprint": evaluation.evaluation_fingerprint,
        "config_fingerprint": evaluation.config_fingerprint,
        "rubric_version": evaluation.rubric_version,
        "policy_version": evaluation.policy_version,
        "engine_name": evaluation.engine_name,
        "engine_configuration": evaluation.engine_configuration,
        "model_version": evaluation.model_version,
        "decision": evaluation.decision,
        "deterministic_result": evaluation.deterministic_result,
        "jev_signals": evaluation.jev_signals,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_public_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))[:1500]
    except ValueError:
        return None


def _clean_label(value: str | None, limit: int) -> str:
    cleaned = _WHITESPACE.sub(" ", value or "").strip()
    # Telegram formatting and control characters are unnecessary in labels.
    cleaned = "".join(char for char in cleaned if char.isprintable())
    return cleaned[:limit] or "Unknown"


def _item_result(session: Session, row: OpportunityNotification) -> NotificationItemResult:
    job = session.get(Job, row.job_id)
    company = job.company.name if job is not None and job.company is not None else "Unknown company"
    return NotificationItemResult(
        job_id=row.job_id,
        company=_clean_label(company, 160),
        title=_clean_label(job.title if job is not None else "Unknown title", 200),
        status=row.status,
        failure_reason=row.failure_reason,
    )


def _recover_interrupted_dispatches(session: Session) -> None:
    """Mark old in-flight claims ambiguous without risking an automatic resend."""

    cutoff = datetime.now(UTC) - timedelta(minutes=2)
    rows = session.scalars(
        select(OpportunityNotification).where(
            OpportunityNotification.status == OpportunityNotificationStatus.PENDING.value,
            OpportunityNotification.dispatch_started.is_(True),
            OpportunityNotification.dispatch_started_at < cutoff,
        )
    ).all()
    for row in rows:
        row.status = OpportunityNotificationStatus.FAILED.value
        row.failure_reason = "delivery_outcome_unknown_after_interruption"
        row.retryable = False
        row.dispatch_started = False
        row.dispatch_started_at = None


def _validate_threshold(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("notification review threshold must be between 0 and 100")
