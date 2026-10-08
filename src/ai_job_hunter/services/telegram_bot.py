"""Long-polling Telegram bot that drafts cover letters from alert buttons.

The bot only answers the configured chat, sends plain text, never submits
anything anywhere, and never surfaces the bot token or request URL in errors.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import SecretStr

from ai_job_hunter.company_hunter.notify import (
    CONNECTION_ACCEPTED_PREFIX,
    CONNECTION_SENT_PREFIX,
    CONNECTION_SKIP_PREFIX,
    HUNTER_DRAFT_PREFIX,
)
from ai_job_hunter.services.cover_letters import CoverLetterDraft, CoverLetterError
from ai_job_hunter.services.notifications import (
    APPLICATION_PACK_CALLBACK_PREFIX,
    COVER_LETTER_CALLBACK_PREFIX,
    COVER_LETTER_SPANISH_CALLBACK_PREFIX,
    DISMISS_REASON_CODES,
    INTERVIEW_PREP_CALLBACK_PREFIX,
    SAVE_REASON_CODES,
    feedback_reason_keyboard,
)

MAX_MESSAGE_CHARS = 4000
MAX_DOCUMENT_BYTES = 45 * 1024 * 1024
_BACKOFF_START = 5.0
_BACKOFF_MAX = 60.0


class TelegramBotError(RuntimeError):
    """A Telegram Bot API call failed; carries only a status code or type name."""

    def __init__(self, status_code: int | None = None, kind: str | None = None) -> None:
        self.status_code = status_code
        self.kind = kind
        detail = f"HTTP {status_code}" if status_code is not None else (kind or "unknown error")
        super().__init__(f"Telegram bot request failed ({detail}).")


class TelegramBotClient:
    """Small Bot API client for getUpdates, answerCallbackQuery and plain sendMessage."""

    def __init__(
        self,
        bot_token: SecretStr | str,
        chat_id: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        token = bot_token.get_secret_value() if isinstance(bot_token, SecretStr) else bot_token
        if not isinstance(token, str) or not token.strip() or not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError("Telegram bot configuration is incomplete.")
        self._bot_token = token.strip()
        self._chat_id = chat_id.strip()
        self._client = client
        self._timeout = timeout

    def get_updates(self, offset: int | None, timeout_seconds: int = 50) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": json.dumps(["callback_query", "message"]),
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramBotError(kind="InvalidResponse")
        return [item for item in result if isinstance(item, dict)]

    def answer_callback_query(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def send_text(
        self, text: str, reply_markup: dict[str, Any] | None = None, reply_to: int | None = None
    ) -> int | None:
        """Send ``text`` (split if long); returns the id of the first message Telegram created."""

        chunks = split_text(text)
        first_id: int | None = None
        for index, chunk in enumerate(chunks):
            data: dict[str, Any] = {"chat_id": self._chat_id, "text": chunk}
            if reply_to is not None and index == 0:
                data["reply_to_message_id"] = reply_to
                data["allow_sending_without_reply"] = "true"
            if reply_markup is not None and index == len(chunks) - 1:
                data["reply_markup"] = json.dumps(reply_markup, separators=(",", ":"))
            result = self._call("sendMessage", data)
            if index == 0 and isinstance(result, dict) and isinstance(result.get("message_id"), int):
                first_id = result["message_id"]
        return first_id

    def send_document(self, path: Path, caption: str | None = None) -> bool:
        """Upload one local file; returns False (nothing sent) when it is missing or too large."""

        try:
            if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
                return False
            content = path.read_bytes()
        except OSError:
            return False
        data: dict[str, Any] = {"chat_id": self._chat_id}
        if caption:
            data["caption"] = caption
        self._call("sendDocument", data, files={"document": (path.name, content)})
        return True

    def send_document_group(
        self, paths: list[Path], caption: str | None = None, reply_to: int | None = None
    ) -> bool:
        """Send files as one grouped message (optionally replying to a message).

        Returns False without sending when any file is missing or too large.
        """

        files: dict[str, Any] = {}
        media: list[dict[str, Any]] = []
        for index, path in enumerate(paths):
            try:
                if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
                    return False
                files[f"file{index}"] = (path.name, path.read_bytes())
            except OSError:
                return False
            media.append({"type": "document", "media": f"attach://file{index}"})
        if not media:
            return False
        if caption:
            media[-1]["caption"] = caption[:1024]
        data: dict[str, Any] = {"chat_id": self._chat_id, "media": json.dumps(media)}
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
            data["allow_sending_without_reply"] = "true"
        self._call("sendMediaGroup", data, files=files)
        return True

    def _call(self, method: str, data: dict[str, Any], files: dict[str, Any] | None = None) -> Any:
        client = self._client or httpx.Client()
        should_close = self._client is None
        endpoint = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        try:
            # Long polling keeps the request open past the Telegram-side timeout.
            if files is None:
                response = client.post(endpoint, data=data, timeout=self._timeout)
            else:
                response = client.post(endpoint, data=data, files=files, timeout=self._timeout)
        except httpx.HTTPError as error:
            # Never chain/format the httpx exception: it may contain the token URL.
            raise TelegramBotError(kind=type(error).__name__) from None
        finally:
            if should_close:
                client.close()
        if response.status_code != 200:
            raise TelegramBotError(status_code=response.status_code)
        try:
            body = response.json()
        except ValueError:
            raise TelegramBotError(kind="InvalidResponse") from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            code = body.get("error_code") if isinstance(body, dict) else None
            raise TelegramBotError(status_code=code if isinstance(code, int) else None)
        return body.get("result")


def split_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split on paragraph boundaries into chunks of at most ``limit`` characters."""

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        while len(paragraph) > limit:
            if current:
                chunks.append(current)
                current = ""
            cut = paragraph.rfind("\n", 0, limit)
            cut = cut if cut > 0 else paragraph.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip("\n ")
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks or [""]


@dataclass(frozen=True, slots=True)
class HunterHandlers:
    """Company Hunter callbacks; each returns plain text for the candidate and sends nothing outside the chat."""

    # company id -> text with the email and LinkedIn DM drafts
    draft_company: Callable[[UUID], str]
    # ("sent" | "accepted" | "skip", request id) -> (button answer, optional reply text)
    connection_action: Callable[[str, UUID], tuple[str, str | None]]
    # (id of the message the candidate replied to, pasted text) -> reply text, or None when not ours
    post_reply: Callable[[int, str], str | None]


_CONNECTION_ACTIONS = {
    CONNECTION_SENT_PREFIX: "sent",
    CONNECTION_ACCEPTED_PREFIX: "accepted",
    CONNECTION_SKIP_PREFIX: "skip",
}


def _parse_hunter(data: Any) -> tuple[str, UUID] | None:
    """("draft" | "sent" | "accepted" | "skip", id) for a Company Hunter button, else None."""

    if not isinstance(data, str):
        return None
    for prefix, action in ((HUNTER_DRAFT_PREFIX, "draft"), *_CONNECTION_ACTIONS.items()):
        if data.startswith(prefix):
            try:
                return action, UUID(data[len(prefix):])
            except ValueError:
                return None
    return None


def _handle_hunter(
    bot: TelegramBotClient,
    callback_id: str,
    action: tuple[str, UUID],
    hunter: HunterHandlers | None,
    reply_to: int | None,
) -> str:
    kind, identifier = action
    if hunter is None:
        _answer(bot, callback_id, "Company Hunter no disponible")
        return "ignored"
    if kind == "draft":
        _answer(bot, callback_id, "Preparando borradores…")
        try:
            text = hunter.draft_company(identifier)
        except CoverLetterError as error:
            bot.send_text(f"No se pudieron preparar los borradores: {error}", reply_to=reply_to)
            return "failed"
        except Exception as error:  # noqa: BLE001 - the bot must keep running
            bot.send_text(
                f"No se pudieron preparar los borradores (error inesperado: {type(error).__name__}).",
                reply_to=reply_to,
            )
            return "failed"
        bot.send_text(text, reply_to=reply_to)
        return "generated"
    try:
        answer, follow_up = hunter.connection_action(kind, identifier)
    except CoverLetterError as error:
        _answer(bot, callback_id, "Hecho, pero no se pudo redactar el mensaje")
        bot.send_text(f"No se pudo redactar el mensaje de seguimiento: {error}", reply_to=reply_to)
        return "failed"
    except Exception as error:  # noqa: BLE001 - the bot must keep running
        _answer(bot, callback_id, f"No se pudo guardar ({type(error).__name__})")
        return "failed"
    _answer(bot, callback_id, answer)
    if follow_up:
        bot.send_text(follow_up, reply_to=reply_to)
    return "connection"


def _handle_message(
    message: dict[str, Any],
    chat_id: str,
    bot: TelegramBotClient,
    hunter: HunterHandlers | None,
    record_note: Callable[[UUID | None, int, str], bool] | None = None,
    prompts: dict[int, UUID] | None = None,
) -> str:
    """A text reply to a LinkedIn-queue message regenerates that person's note; a reply to an alert (or to the
    question after a vote) is stored as the user's opinion of that offer."""

    chat = message.get("chat")
    origin = chat.get("id") if isinstance(chat, dict) else None
    if origin is None or str(origin) != str(chat_id).strip():
        return "ignored"
    text = message.get("text")
    reply = message.get("reply_to_message")
    replied_id = reply.get("message_id") if isinstance(reply, dict) else None
    own_id = message.get("message_id")
    own_reply = own_id if isinstance(own_id, int) and not isinstance(own_id, bool) else None
    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(replied_id, int)
        or isinstance(replied_id, bool)
    ):
        return "ignored"
    if hunter is not None:
        try:
            answer = hunter.post_reply(replied_id, text)
        except CoverLetterError as error:
            bot.send_text(f"No se pudo regenerar la nota: {error}", reply_to=own_reply)
            return "failed"
        except Exception as error:  # noqa: BLE001 - the bot must keep running
            bot.send_text(f"No se pudo regenerar la nota (error inesperado: {type(error).__name__}).")
            return "failed"
        if answer is not None:
            bot.send_text(answer, reply_to=own_reply)
            return "regenerated"
    if record_note is None:
        return "ignored"
    try:
        stored = record_note((prompts or {}).get(replied_id), replied_id, text)
    except Exception as error:  # noqa: BLE001 - the bot must keep running
        bot.send_text(f"No se pudo guardar tu opinión ({type(error).__name__}).", reply_to=own_reply)
        return "failed"
    if not stored:
        return "ignored"
    bot.send_text("📝 Anotado, gracias.", reply_to=own_reply)
    return "note"


def _parse_request(data: Any) -> tuple[UUID, str] | None:
    """Return (job_id, language) for a cover-letter callback, else None."""

    if not isinstance(data, str):
        return None
    for prefix, language in (
        (COVER_LETTER_CALLBACK_PREFIX, "auto"),
        (COVER_LETTER_SPANISH_CALLBACK_PREFIX, "es"),
    ):
        if data.startswith(prefix):
            try:
                return UUID(data[len(prefix):]), language
            except ValueError:
                return None
    return None


def handle_update(
    update: dict[str, Any],
    *,
    chat_id: str,
    bot: TelegramBotClient,
    generate: Callable[[UUID, str], CoverLetterDraft],
    generated: dict[tuple[UUID, str], CoverLetterDraft],
    record_feedback: Callable[[UUID, str, str | None], None] | None = None,
    prepare: Callable[[UUID], Any] | None = None,
    prepared: dict[UUID, Any] | None = None,
    prepare_interview: Callable[[UUID], Any] | None = None,
    interviews: dict[UUID, Any] | None = None,
    hunter: HunterHandlers | None = None,
    record_note: Callable[[UUID | None, int, str], bool] | None = None,
    prompts: dict[int, UUID] | None = None,
) -> str:
    """Handle one update and return "ignored", "generated", "failed", "duplicate", "feedback",
    "connection", "regenerated" or "note".

    Updates are handled one at a time, so a second tap on the same button
    arrives after the first letter is done; ``generated`` makes it resend that
    letter instead of paying for a new one.
    """

    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        message_update = update.get("message")
        if isinstance(message_update, dict):
            return _handle_message(message_update, chat_id, bot, hunter, record_note, prompts)
        return "ignored"
    message = callback.get("message")
    chat = message.get("chat") if isinstance(message, dict) else None
    origin = chat.get("id") if isinstance(chat, dict) else None
    if origin is None or str(origin) != str(chat_id).strip():
        return "ignored"
    callback_id = str(callback.get("id", ""))
    raw_message_id = message.get("message_id") if isinstance(message, dict) else None
    alert_message_id = raw_message_id if isinstance(raw_message_id, int) and not isinstance(raw_message_id, bool) else None
    feedback = _parse_feedback(callback.get("data"))
    if feedback is not None:
        return _handle_feedback(bot, callback_id, feedback, record_feedback, alert_message_id, prompts)
    hunter_action = _parse_hunter(callback.get("data"))
    if hunter_action is not None:
        return _handle_hunter(bot, callback_id, hunter_action, hunter, alert_message_id)
    pack_job = _parse_pack(callback.get("data"))
    if pack_job is not None:
        return _handle_pack(bot, callback_id, pack_job, prepare, prepared if prepared is not None else {}, alert_message_id)
    interview_job = _parse_interview(callback.get("data"))
    if interview_job is not None:
        return _handle_interview(
            bot, callback_id, interview_job, prepare_interview, interviews if interviews is not None else {}, alert_message_id
        )
    request = _parse_request(callback.get("data"))
    if request is None:
        _answer(bot, callback_id, "Acción no reconocida")
        return "ignored"
    job_id, language = request
    key = (job_id, language)
    if key in generated:
        _answer(bot, callback_id, "Ya la generé; te la reenvío")
        _send_draft(bot, generated[key], reply_to=alert_message_id)
        return "duplicate"
    _answer(bot, callback_id, "Generando cover letter…")
    try:
        draft = generate(job_id, language)
    except CoverLetterError as error:
        bot.send_text(f"No se pudo generar la cover letter: {error}")
        return "failed"
    except Exception as error:  # noqa: BLE001 - the bot must keep running
        bot.send_text(
            f"No se pudo generar la cover letter (error inesperado: {type(error).__name__})."
        )
        return "failed"
    generated[key] = draft
    _send_draft(bot, draft, reply_to=alert_message_id)
    return "generated"


def _parse_pack(data: Any) -> UUID | None:
    if not isinstance(data, str) or not data.startswith(APPLICATION_PACK_CALLBACK_PREFIX):
        return None
    try:
        return UUID(data[len(APPLICATION_PACK_CALLBACK_PREFIX):])
    except ValueError:
        return None


def _handle_pack(
    bot: TelegramBotClient,
    callback_id: str,
    job_id: UUID,
    prepare: Callable[[UUID], Any] | None,
    prepared: dict[UUID, Any],
    reply_to: int | None,
) -> str:
    if prepare is None:
        _answer(bot, callback_id, "Preparar candidatura no disponible")
        return "ignored"
    if job_id in prepared:
        _answer(bot, callback_id, "Ya la preparé; te la reenvío")
        _send_pack(bot, prepared[job_id], reply_to)
        return "duplicate"
    _answer(bot, callback_id, "Preparando candidatura (CV, carta y respuestas)…")
    try:
        pack = prepare(job_id)
    except CoverLetterError as error:
        bot.send_text(f"No se pudo preparar la candidatura: {error}", reply_to=reply_to)
        return "failed"
    except Exception as error:  # noqa: BLE001 - the bot must keep running
        bot.send_text(f"No se pudo preparar la candidatura (error inesperado: {type(error).__name__}).", reply_to=reply_to)
        return "failed"
    prepared[job_id] = pack
    _send_pack(bot, pack, reply_to)
    return "generated"


def _send_pack(bot: TelegramBotClient, pack: Any, reply_to: int | None) -> None:
    """CV + letter as one grouped reply, then the form answers as text. Nothing is submitted."""

    letter = pack.letter
    files = [path for path in (pack.cv_docx, pack.cv_pdf, letter.docx_path, letter.pdf_path) if path is not None]
    cv_line = "CV adaptado a la oferta" if pack.cv_tailored else (pack.cv_note or "CV base")
    caption = (
        f"📝 Candidatura — {pack.company} · {pack.title}\n{cv_line} + cover letter.\n"
        "Revísalo todo antes de usarlo; no se ha enviado nada."
    )
    sent = False
    if files:
        try:
            sent = bot.send_document_group(files, caption=caption, reply_to=reply_to)
        except TelegramBotError:
            sent = False
    if not sent:
        bot.send_text(caption + "\n\n" + letter.text, reply_to=reply_to)
    bot.send_text("📋 Respuestas para el formulario\n\n" + pack.answers_text.replace("**", ""), reply_to=reply_to)


def _parse_interview(data: Any) -> UUID | None:
    if not isinstance(data, str) or not data.startswith(INTERVIEW_PREP_CALLBACK_PREFIX):
        return None
    try:
        return UUID(data[len(INTERVIEW_PREP_CALLBACK_PREFIX):])
    except ValueError:
        return None


def _handle_interview(
    bot: TelegramBotClient,
    callback_id: str,
    job_id: UUID,
    prepare_interview: Callable[[UUID], Any] | None,
    interviews: dict[UUID, Any],
    reply_to: int | None,
) -> str:
    if prepare_interview is None:
        _answer(bot, callback_id, "Preparar entrevista no disponible")
        return "ignored"
    if job_id in interviews:
        _answer(bot, callback_id, "Ya la preparé; te la reenvío")
        _send_interview(bot, interviews[job_id], reply_to)
        return "duplicate"
    _answer(bot, callback_id, "Preparando entrevista…")
    try:
        brief = prepare_interview(job_id)
    except CoverLetterError as error:
        bot.send_text(f"No se pudo preparar la entrevista: {error}", reply_to=reply_to)
        return "failed"
    except Exception as error:  # noqa: BLE001 - the bot must keep running
        bot.send_text(f"No se pudo preparar la entrevista (error inesperado: {type(error).__name__}).", reply_to=reply_to)
        return "failed"
    interviews[job_id] = brief
    _send_interview(bot, brief, reply_to)
    return "generated"


def _send_interview(bot: TelegramBotClient, brief: Any, reply_to: int | None) -> None:
    """Word + PDF as one grouped reply; the Markdown text if they can't be sent. Nothing is sent elsewhere."""

    files = [path for path in (brief.docx_path, brief.pdf_path) if path is not None]
    caption = (
        f"🎯 Preparación de entrevista — {brief.company} · {brief.title}\n"
        "Revísala y contrasta los datos de la empresa; no se ha enviado nada."
    )
    if files and not brief.render_error:
        try:
            if bot.send_document_group(files, caption=caption, reply_to=reply_to):
                return
        except TelegramBotError:
            pass  # fall back to text so the paid brief is still delivered
    bot.send_text(caption + "\n\n" + brief.markdown.replace("**", ""), reply_to=reply_to)


def _parse_feedback(data: Any) -> tuple[str, UUID, str | None] | None:
    """('SAVED'|'DISMISSED', job_id, reason) from up:/dn:/ur:<code>:/dr:<code>: callbacks."""

    if not isinstance(data, str):
        return None
    kind, _, rest = data.partition(":")
    state = {"up": "SAVED", "dn": "DISMISSED", "ur": "SAVED", "dr": "DISMISSED"}.get(kind)
    if state is None:
        return None
    reason = None
    if kind in {"ur", "dr"}:
        code, _, rest = rest.partition(":")
        codes = SAVE_REASON_CODES if kind == "ur" else DISMISS_REASON_CODES
        if code not in codes:
            return None
        reason = codes[code][0]
    try:
        return state, UUID(rest), reason
    except ValueError:
        return None


def _handle_feedback(
    bot: TelegramBotClient,
    callback_id: str,
    feedback: tuple[str, UUID, str | None],
    record_feedback: Callable[[UUID, str, str | None], None] | None,
    alert_message_id: int | None = None,
    prompts: dict[int, UUID] | None = None,
) -> str:
    state, job_id, reason = feedback
    if record_feedback is None:
        _answer(bot, callback_id, "Feedback no disponible")
        return "ignored"
    try:
        record_feedback(job_id, state, reason)
    except Exception as error:  # noqa: BLE001 - the bot must keep running
        _answer(bot, callback_id, f"No se pudo guardar ({type(error).__name__})")
        return "failed"
    saved = state == "SAVED"
    if reason is None:
        _answer(bot, callback_id, "Guardada 👍" if saved else "Descartada 👎")
        # No list of reasons: the opinion is free text, written as a reply to this message or to the alert itself.
        prompt = (
            "👍 Guardada. Si quieres, cuéntame qué te gusta y qué no: responde a este mensaje con tu opinión."
            if saved
            else "👎 Descartada. Si quieres, cuéntame por qué: responde a este mensaje con tu opinión."
        )
        keyboard = (
            {"inline_keyboard": [[{"text": "🎯 Preparar entrevista", "callback_data": f"{INTERVIEW_PREP_CALLBACK_PREFIX}{job_id}"}]]}
            if saved
            else None
        )
        prompt_id = bot.send_text(prompt, reply_markup=keyboard, reply_to=alert_message_id)
        if prompts is not None and prompt_id is not None:
            prompts[prompt_id] = job_id
    else:
        _answer(bot, callback_id, "Motivo guardado, gracias")
    return "feedback"


def _answer(bot: TelegramBotClient, callback_id: str, text: str) -> None:
    # Telegram rejects answers to old taps (e.g. made while the bot was off);
    # the request itself is still valid, so carry on.
    try:
        bot.answer_callback_query(callback_id, text)
    except TelegramBotError:
        pass


def _send_draft(bot: TelegramBotClient, draft: CoverLetterDraft, reply_to: int | None = None) -> None:
    """Reply to the alert with the Word + PDF files only; fall back to text if they can't be sent.

    Keeping the letter attached to its alert (instead of a long text message
    in the chat) leaves the alert feed readable.
    """

    files = [path for path in (draft.docx_path, draft.pdf_path) if path is not None]
    caption = f"✍️ Cover letter — {draft.company} · {draft.title}\nBorrador para revisar; no se ha enviado a nadie."
    if files and not draft.render_error:
        try:
            if bot.send_document_group(files, caption=caption, reply_to=reply_to):
                return
        except TelegramBotError:
            pass  # fall back to text so the paid draft is still delivered
    bot.send_text(
        f"✍️ Cover letter — {draft.company} — {draft.title}\n"
        "(Borrador: revísalo antes de usarlo. No se ha enviado a nadie.)\n\n"
        f"{draft.text}",
        reply_to=reply_to,
    )


def load_offset(path: Path) -> int | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("offset")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def save_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    os.replace(temporary, path)


def run_bot(
    bot: TelegramBotClient,
    *,
    chat_id: str,
    generate: Callable[[UUID, str], CoverLetterDraft],
    offset_path: Path,
    record_feedback: Callable[[UUID, str, str | None], None] | None = None,
    prepare: Callable[[UUID], Any] | None = None,
    prepare_interview: Callable[[UUID], Any] | None = None,
    hunter: HunterHandlers | None = None,
    record_note: Callable[[UUID | None, int, str], bool] | None = None,
    max_cycles: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda message: print(message, flush=True),
) -> None:
    """Long-poll until interrupted (or ``max_cycles`` polls, used by tests)."""

    offset = load_offset(offset_path)
    generated: dict[tuple[UUID, str], CoverLetterDraft] = {}
    prepared: dict[UUID, Any] = {}
    interviews: dict[UUID, Any] = {}
    prompts: dict[int, UUID] = {}
    backoff = _BACKOFF_START
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        try:
            updates = bot.get_updates(offset)
            for update in updates:
                try:
                    outcome = handle_update(
                        update,
                        chat_id=chat_id,
                        bot=bot,
                        generate=generate,
                        generated=generated,
                        record_feedback=record_feedback,
                        prepare=prepare,
                        prepared=prepared,
                        prepare_interview=prepare_interview,
                        interviews=interviews,
                        hunter=hunter,
                        record_note=record_note,
                        prompts=prompts,
                    )
                    log(f"update {update.get('update_id')}: {outcome}")
                finally:
                    # Advance even when replying fails so a paid generation is never repeated.
                    update_id = update.get("update_id")
                    if isinstance(update_id, int) and not isinstance(update_id, bool):
                        offset = update_id + 1
                        save_offset(offset_path, offset)
            backoff = _BACKOFF_START
        except (TelegramBotError, httpx.HTTPError) as error:
            # Errors never contain the token (see TelegramBotClient).
            log(f"telegram poll failed: {error if isinstance(error, TelegramBotError) else type(error).__name__}; retrying in {backoff:.0f}s")
            sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
