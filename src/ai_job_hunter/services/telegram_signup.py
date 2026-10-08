"""Telegram side of the sign-up: other people's chats, the owner's /invite, and CV downloads.

The bot used to answer only the owner's chat. This router sits in front of the old handlers: a message or button press from
any other private chat goes through ``services.onboarding`` (or the person's own commands once signed up), and the
owner's ``/invite`` creates a single-use code. Everything else is left to the old handlers (it returns ``None``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.models.user import User, UserStatus
from ai_job_hunter.services import onboarding, preference_learning, profile_edit
from ai_job_hunter.services.onboarding import Event, ProfileExtractor, Reply
from ai_job_hunter.services.telegram_bot import (
    TelegramBotClient,
    TelegramBotError,
    _handle_feedback,
    _handle_message,
    _parse_feedback,
    _parse_interview,
    _parse_request,
)
from ai_job_hunter.services.person_documents import QuotaExceeded
from ai_job_hunter.services.users import get_owner

MAX_CV_BYTES = 5 * 1024 * 1024
CV_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
NEED_INVITATION = "Esta beta es solo con invitación. Pídele un código a quien te habló del bot y escribe /start CÓDIGO."
BAD_CODE = {
    "unknown": "Ese código no existe. Revísalo y escríbelo otra vez: /start CÓDIGO",
    "used": "Ese código ya se usó. Pide uno nuevo.",
    "expired": "Ese código ha caducado. Pide uno nuevo.",
}


class SignupHandlers:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        extract: ProfileExtractor,
        owner_chat_id: str,
        record_feedback: Callable[[UUID, str, str | None], None] | None = None,
        record_note: Callable[[UUID | None, int, str], bool] | None = None,
        documents: Any | None = None,
    ) -> None:
        self._documents = documents  # a PersonDocuments: letters and interview briefs for people
        self._sessions = session_factory
        self._extract = extract
        self._record_feedback = record_feedback
        self._record_note = record_note
        self._prompts: dict[int, UUID] = {}
        self._owner_chat = str(owner_chat_id).strip()
        self._username: str | None = None

    # -- entry point ------------------------------------------------------------------------------------------------
    def handle(self, update: dict[str, Any], bot: TelegramBotClient) -> str | None:
        """Outcome when this update was for the sign-up; ``None`` leaves it to the owner's handlers."""

        callback = update.get("callback_query")
        message = callback.get("message") if isinstance(callback, dict) else update.get("message")
        chat = message.get("chat") if isinstance(message, dict) else None
        if not isinstance(chat, dict) or chat.get("type") != "private" or chat.get("id") is None:
            return None
        chat_id = str(chat["id"])
        data = callback.get("data") if isinstance(callback, dict) else None
        if isinstance(data, str) and data.startswith(preference_learning.UNDO_PREFIX):
            return self._undo(bot, chat_id, callback)
        if chat_id == self._owner_chat:
            return self._owner_command(update, bot) if not isinstance(callback, dict) else None

        person = bot.with_chat(chat_id)
        with self._sessions() as session:
            outcome = self._for_person(session, person, chat_id, update, callback if isinstance(callback, dict) else None)
            session.commit()
        return outcome

    def _undo(self, bot: TelegramBotClient, chat_id: str, callback: dict[str, Any]) -> str:
        """The "Undo" button of a learned change, for the owner and for everyone else."""

        try:
            change_id = UUID(str(callback["data"])[len(preference_learning.UNDO_PREFIX):])
        except ValueError:
            return "signup_ignored"
        with self._sessions() as session:
            user = session.scalar(select(User).where(User.telegram_chat_id == chat_id))
            if user is None and chat_id == self._owner_chat:
                user = get_owner(session)
            if user is None:
                return "signup_ignored"
            with acting_as(user.id):
                answer = preference_learning.undo(session, user, change_id)
            session.commit()
        try:
            bot.answer_callback_query(str(callback.get("id", "")), answer)
        except TelegramBotError:
            pass
        return "preference_undone"

    # -- the owner --------------------------------------------------------------------------------------------------
    def _owner_command(self, update: dict[str, Any], bot: TelegramBotClient) -> str | None:
        text = (update.get("message") or {}).get("text")
        if not isinstance(text, str) or onboarding.COMMAND_ALIASES.get(text.strip().split()[0].casefold() if text.strip() else "", "") != "/invite" and text.strip().split()[:1] != ["/invite"]:
            return None
        with self._sessions() as session:
            owner = get_owner(session)
            if owner is None:
                bot.send_text("No encuentro tu usuario de propietario: importa tu perfil con users_cli import-owner.")
                return "invite_failed"
            invitation = onboarding.create_invitation(session, owner)
            code = invitation.code
            session.commit()
        link = ""
        try:
            self._username = self._username or bot.username()
        except TelegramBotError:
            pass
        if self._username:
            link = f"\nEnlace directo: https://t.me/{self._username}?start={code}"
        bot.send_text(
            f"🎟 Invitación (un solo uso, caduca en {onboarding.INVITATION_DAYS} días): {code}\n"
            f"Que la persona abra el bot y escriba: /start {code}{link}"
        )
        return "invited"

    # -- other people -----------------------------------------------------------------------------------------------
    def _for_person(
        self, session: Session, person: TelegramBotClient, chat_id: str, update: dict[str, Any], callback: dict[str, Any] | None
    ) -> str:
        user = session.scalar(select(User).where(User.telegram_chat_id == chat_id))
        message = callback.get("message") if callback else update.get("message")
        text = (message or {}).get("text") if not callback else None
        words = text.strip().split() if isinstance(text, str) else []

        if user is None:
            if words[:1] == ["/start"] and len(words) > 1:
                user, result = onboarding.redeem_invitation(session, words[1], chat_id)
                if user is None:
                    person.send_text(BAD_CODE.get(result, NEED_INVITATION))
                    return "signup_refused"
                self._say(person, onboarding.welcome(user))
                return "signup_started"
            person.send_text(NEED_INVITATION)
            return "signup_refused"

        if callback is not None:
            return self._press(session, person, user, callback)
        if user.status == UserStatus.ONBOARDING.value and words[:1] == ["/start"]:
            self._say(person, onboarding.handle(session, user, Event(kind="text", text=""), self._extract))
            return "signup_step"
        if words and words[0].startswith("/"):
            replies = onboarding.handle_command(session, user, text) if user.consent_at else []
            self._say(person, replies or [Reply("No conozco ese comando. Prueba /profile, /my_data, /pause, /resume o /erase.")])
            return "signup_command"
        if user.status != UserStatus.ONBOARDING.value:
            if profile_edit.is_editing(user) and isinstance(text, str) and text.strip():
                self._say(person, profile_edit.text(session, user, text))
                return "profile_edit"
            if isinstance(message, dict) and message.get("reply_to_message") and self._record_note is not None:
                with acting_as(user.id):  # an opinion written as a reply to one of this person's alerts
                    return _handle_message(message, chat_id, person, None, self._record_note, self._prompts)
            self._say(person, [Reply("Te aviso cuando haya ofertas. Comandos: /profile, /my_data, /pause, /resume, /erase.")])
            return "signup_idle"

        document = (message or {}).get("document")
        if isinstance(document, dict):
            return self._document(session, person, user, document)
        if isinstance(text, str) and text.strip():
            self._say(person, onboarding.handle(session, user, Event(kind="text", text=text), self._extract))
            return "signup_step"
        return "signup_ignored"

    def _press(self, session: Session, person: TelegramBotClient, user: User, callback: dict[str, Any]) -> str:
        data = callback.get("data")
        feedback = _parse_feedback(data)
        if feedback is not None and user.status != UserStatus.ONBOARDING.value:
            alert_id = (callback.get("message") or {}).get("message_id")
            with acting_as(user.id):  # their vote on their alert; the handler answers the tap itself
                return _handle_feedback(
                    person, str(callback.get("id", "")), feedback, self._record_feedback,
                    alert_id if isinstance(alert_id, int) and not isinstance(alert_id, bool) else None, self._prompts,
                )
        if isinstance(data, str) and data.startswith("pf:") and user.status != UserStatus.ONBOARDING.value:
            try:
                person.answer_callback_query(str(callback.get("id", "")), "")
            except TelegramBotError:
                pass
            self._say(person, profile_edit.press(session, user, data))
            return "profile_edit"
        document = self._document_request(data)
        if document is not None and self._documents is not None and user.status != UserStatus.ONBOARDING.value:
            return self._write_document(person, user, callback, *document)
        try:
            unavailable = "" if isinstance(data, str) and data.startswith("ob:") else "Esto aún no está disponible en la beta"
            person.answer_callback_query(str(callback.get("id", "")), unavailable)
        except TelegramBotError:
            pass
        if not isinstance(data, str) or not data.startswith("ob:"):
            return "signup_ignored"
        if data.startswith("ob:erase:"):
            self._say(person, onboarding.handle_erase_press(session, user, data))
            return "signup_erased" if data.endswith("yes") else "signup_command"
        self._say(person, onboarding.handle(session, user, Event(kind="press", data=data), self._extract))
        return "signup_step"

    @staticmethod
    def _document_request(data: Any) -> tuple[str, UUID, str] | None:
        """(kind, job id, language) for the letter and interview buttons of an alert."""

        letter = _parse_request(data)
        if letter is not None:
            return "LETTER", letter[0], letter[1]
        interview = _parse_interview(data)
        return ("INTERVIEW", interview, "auto") if interview is not None else None

    def _write_document(
        self, person: TelegramBotClient, user: User, callback: dict[str, Any], kind: str, job_id: UUID, language: str
    ) -> str:
        callback_id = str(callback.get("id", ""))
        alert_id = (callback.get("message") or {}).get("message_id")
        reply_to = alert_id if isinstance(alert_id, int) and not isinstance(alert_id, bool) else None
        try:
            person.answer_callback_query(callback_id, "Escribiendo…" if kind == "LETTER" else "Preparando…")
        except TelegramBotError:
            pass
        try:
            result = self._documents.letter(user.id, job_id, language) if kind == "LETTER" else self._documents.interview(user.id, job_id)
        except QuotaExceeded as error:
            person.send_text(str(error), reply_to=reply_to)
            return "document_refused"
        except Exception:  # noqa: BLE001 - the bot must keep running; provider details never reach the person
            person.send_text("No he podido escribirlo ahora. Inténtalo más tarde.", reply_to=reply_to)
            return "document_failed"
        title = "✍️ Carta" if kind == "LETTER" else "🎯 Entrevista"
        person.send_text(
            f"{title} — {result.company} — {result.title}\n"
            f"(Borrador: revísalo y añade tu nombre. No se ha enviado a nadie.)\n\n{result.text}",
            reply_to=reply_to,
        )
        return "document_resent" if result.reused else "document_written"

    def _document(self, session: Session, person: TelegramBotClient, user: User, document: dict[str, Any]) -> str:
        if document.get("mime_type") not in CV_MIME_TYPES or int(document.get("file_size") or 0) > MAX_CV_BYTES:
            person.send_text("Envíame el CV como PDF o Word (.docx) de menos de 5 MB, o pega su texto.")
            return "signup_step"
        try:
            content = person.download_file(str(document.get("file_id")), max_bytes=MAX_CV_BYTES)
        except TelegramBotError:
            person.send_text("No he podido descargar el archivo. Inténtalo de nuevo o pega el texto del CV.")
            return "signup_step"
        person.send_text("Leyendo tu CV…")
        event = Event(kind="document", filename=str(document.get("file_name") or "cv"), content=content)
        self._say(person, onboarding.handle(session, user, event, self._extract))
        return "signup_step"

    @staticmethod
    def _say(person: TelegramBotClient, replies: list[Reply]) -> None:
        for reply in replies:
            markup = (
                {"inline_keyboard": [[{"text": b.label, "callback_data": b.data} for b in row] for row in reply.buttons]}
                if reply.buttons
                else None
            )
            person.send_text(reply.text, reply_markup=markup)
