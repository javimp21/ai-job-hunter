"""Company Hunter handlers for the Telegram bot (buttons and pasted-post replies)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.notify import format_drafts
from ai_job_hunter.company_hunter.queue import (
    ConnectionQueueError,
    build_follow_up,
    mark_accepted,
    mark_sent,
    mark_skipped,
    regenerate_note_from_post,
)
from ai_job_hunter.company_hunter.service import draft_for_company
from ai_job_hunter.company_hunter.writing import DEFAULT_CV_DIR
from ai_job_hunter.models import ConnectionRequest
from ai_job_hunter.services.cover_letters import DEFAULT_STYLE_GUIDE_PATH, MessagesClient
from ai_job_hunter.services.telegram_bot import HunterHandlers


def build_handlers(
    session_factory: Callable[[], Session],
    *,
    client: MessagesClient | None = None,
    cv_dir: Path = DEFAULT_CV_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
) -> HunterHandlers:
    """Handlers that open one session per request, like the cover-letter bot callbacks."""

    def draft_company(company_id: UUID) -> str:
        with session_factory() as session:
            outcome = draft_for_company(
                session, company_id, client=client, cv_dir=cv_dir, style_guide_path=style_guide_path
            )
            session.commit()
            return format_drafts(outcome)

    def connection_action(action: str, request_id: UUID) -> tuple[str, str | None]:
        with session_factory() as session:
            try:
                if action == "sent":
                    mark_sent(session, request_id)
                    session.commit()
                    return "Marcada como enviada ✅", None
                if action == "skip":
                    mark_skipped(session, request_id)
                    session.commit()
                    return "Saltada: no se vuelve a sugerir en 60 días ⏭️", None
                if action == "accepted":
                    request = mark_accepted(session, request_id)
                    session.commit()  # the acceptance is recorded even if the draft fails
                    name = request.contact.name
                    draft = build_follow_up(
                        session, request_id, client=client, cv_dir=cv_dir, style_guide_path=style_guide_path
                    )
                    session.commit()
                    return (
                        "Marcada como aceptada 🤝",
                        f"💬 Mensaje para {name} (borrador; envíalo tú a mano en LinkedIn):\n\n{draft}",
                    )
            except ConnectionQueueError as error:
                session.rollback()
                return str(error), None
        return "Acción no reconocida", None

    def post_reply(message_id: int, text: str) -> str | None:
        with session_factory() as session:
            request = session.scalar(
                select(ConnectionRequest).where(ConnectionRequest.telegram_message_id == str(message_id))
            )
            if request is None:
                return None
            try:
                updated = regenerate_note_from_post(
                    session, request.id, text, client=client, cv_dir=cv_dir, style_guide_path=style_guide_path
                )
            except ConnectionQueueError as error:
                session.rollback()
                return str(error)
            session.commit()
            return (
                f"📝 Nota regenerada para {updated.contact.name} a partir de su post "
                f"({len(updated.note)}/300):\n\n{updated.note}"
            )

    return HunterHandlers(draft_company=draft_company, connection_action=connection_action, post_reply=post_reply)
