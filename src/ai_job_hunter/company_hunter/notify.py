"""Telegram messages for Company Hunter: weekly top companies and the daily LinkedIn queue.

All messages go to the candidate's own chat. Nothing is ever sent to a company
or to LinkedIn. Messages are HTML (``TelegramProvider`` style), so every
dynamic value is escaped.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.ranking import CompanyFit
from ai_job_hunter.company_hunter.service import DraftOutcome
from ai_job_hunter.models import Company, ConnectionRequest, Contact
from ai_job_hunter.services.notifications import (
    NotificationProvider,
    TelegramAmbiguousError,
    TelegramRejectedError,
)

HUNTER_DRAFT_PREFIX = "ch:"
CONNECTION_SENT_PREFIX = "cs:"
CONNECTION_ACCEPTED_PREFIX = "ca:"
CONNECTION_SKIP_PREFIX = "ck:"
WEEKLY_TOP = 5
_REASON_CHARS = 170


def _esc(value: str | None, limit: int | None = None) -> str:
    text = " ".join((value or "").split())
    if limit is not None and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text, quote=False)


def contact_line(contact: Contact | None) -> str:
    if contact is None:
        return "sin contacto verificado"
    role = f" — {_esc(contact.title)}" if contact.title else ""
    source = f' (<a href="{html.escape(contact.source_url, quote=True)}">fuente</a>)' if contact.source_url else ""
    return f"{_esc(contact.name)}{role}{source}"


def weekly_message(
    fits: Sequence[CompanyFit],
    best_contacts: dict[UUID, Contact | None],
    *,
    week_label: str,
) -> tuple[str, dict[str, Any] | None]:
    """Top companies with why they fit and whether a verified contact exists, plus ✍️ n buttons."""

    shown = list(fits[:WEEKLY_TOP])
    if not shown:
        return ("🏹 <b>Company Hunter</b> — " + _esc(week_label) + "\nNo hay empresas con evidencia suficiente esta semana.", None)
    lines = [f"🏹 <b>Company Hunter</b> — {_esc(week_label)}", "Empresas que encajan aunque no tengan una oferta abierta:", ""]
    buttons: list[dict[str, str]] = []
    for index, fit in enumerate(shown, start=1):
        reasons = "; ".join(f.reason for f in fit.factors if f.points) or "sin evidencia positiva"
        lines.append(f"<b>{index}. {_esc(fit.name)}</b> · {fit.score}/100 · etapa {fit.stage.value}")
        lines.append(f"   Por qué: {_esc(reasons, _REASON_CHARS)}")
        if fit.unknowns:
            lines.append(f"   Desconocido: {_esc(', '.join(fit.unknowns))}")
        lines.append(f"   Contacto: {contact_line(best_contacts.get(fit.company_id))}")
        lines.append("")
        buttons.append({"text": f"✍️ {index}", "callback_data": f"{HUNTER_DRAFT_PREFIX}{fit.company_id}"})
    lines.append("La puntuación es prioridad de revisión, no probabilidad. Pulsa ✍️ n para preparar borradores (email + LinkedIn). No se envía nada a la empresa.")
    return "\n".join(lines), {"inline_keyboard": [buttons]}


def connection_keyboard(request_id: UUID) -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "✅ Enviada", "callback_data": f"{CONNECTION_SENT_PREFIX}{request_id}"},
            {"text": "🤝 Aceptó", "callback_data": f"{CONNECTION_ACCEPTED_PREFIX}{request_id}"},
            {"text": "⏭️ Saltar", "callback_data": f"{CONNECTION_SKIP_PREFIX}{request_id}"},
        ]]
    }


def connection_header(count: int, day_label: str) -> str:
    return (
        f"🤝 <b>LinkedIn — {count} persona(s) para conectar hoy</b> ({_esc(day_label)})\n"
        "Conexión manual: tú pulsas en LinkedIn; nada se envía desde aquí. "
        "Responde a cualquier mensaje con el texto de un post suyo para regenerar su nota."
    )


def connection_message(
    index: int, total: int, request: ConnectionRequest, contact: Contact, company: Company
) -> str:
    role = f" — {_esc(contact.title)}" if contact.title else ""
    lines = [f"<b>{index}/{total} · {_esc(contact.name)}</b>{role} @ {_esc(company.name)}"]
    if contact.linkedin_url:
        # Stored only when a public non-LinkedIn page we fetched linked to it.
        lines.append(f'Perfil: <a href="{html.escape(contact.linkedin_url, quote=True)}">LinkedIn</a>')
    else:
        lines.append(f"Búscalo en LinkedIn: {_esc(contact.name)} {_esc(company.name)} ({_esc(contact.title)})")
    if contact.source_url:
        lines.append(f'Fuente pública: <a href="{html.escape(contact.source_url, quote=True)}">enlace</a>')
    lines.append("")
    lines.append(f"Nota ({len(request.note)}/300, {request.language}):")
    lines.append(f"<code>{_esc(request.note)}</code>")
    return "\n".join(lines)


@dataclass(slots=True)
class DeliveryResult:
    sent: int = 0
    failed: list[str] = field(default_factory=list)


def send_weekly(provider: NotificationProvider, text: str, keyboard: dict[str, Any] | None) -> None:
    provider.send_message(text, reply_markup=keyboard)


def send_connections(
    session: Session,
    provider: NotificationProvider,
    requests: Sequence[ConnectionRequest],
    *,
    now: datetime,
    day_label: str,
) -> DeliveryResult:
    """Send each person as their own message so a reply identifies the person.

    A request with a stored message id is never sent again (idempotent per
    day); an ambiguous delivery is recorded as ``unknown`` rather than retried.
    """

    result = DeliveryResult()
    pending = [request for request in requests if request.telegram_message_id is None]
    if not pending:
        return result
    try:
        provider.send_message(connection_header(len(requests), day_label))
    except (TelegramRejectedError, TelegramAmbiguousError) as error:
        result.failed.append(f"header: {type(error).__name__}")
        return result
    for index, request in enumerate(requests, start=1):
        if request.telegram_message_id is not None:
            continue
        text = connection_message(index, len(requests), request, request.contact, request.company)
        try:
            sent = provider.send_message(text, reply_markup=connection_keyboard(request.id))
        except TelegramRejectedError as error:
            result.failed.append(f"{request.contact.name}: rejected ({error.status_code})")
            continue
        except TelegramAmbiguousError:
            request.telegram_message_id = "unknown"
            result.failed.append(f"{request.contact.name}: delivery unknown; not retried")
            session.flush()
            continue
        request.telegram_message_id = sent.message_id or "unknown"
        result.sent += 1
        session.flush()
    return result


def format_drafts(outcome: DraftOutcome) -> str:
    """Plain text (the bot sends plain text) with both variants for one company."""

    contact = outcome.contact
    who = (
        f"{contact.name}" + (f" — {contact.title}" if contact.title else "") + (f" ({contact.source_url})" if contact.source_url else "")
        if contact
        else "sin contacto verificado"
    )
    return (
        f"✍️ Borradores — {outcome.company.name} (etapa {outcome.stage.value})\n"
        f"Contacto: {who}\n\n"
        f"— Email —\nAsunto: {outcome.email.subject}\n\n{outcome.email.body}\n\n"
        f"— LinkedIn DM —\n{outcome.linkedin.body}\n\n"
        "Borrador para revisar; no se ha enviado nada a la empresa."
    )
