"""Long-polling Telegram bot that drafts cover letters from alert buttons.

The bot only answers the configured chat, sends plain text, never submits
anything anywhere, and never surfaces the bot token or request URL in errors.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import SecretStr

from ai_job_hunter.services.cover_letters import CoverLetterDraft, CoverLetterError
from ai_job_hunter.services.notifications import (
    COVER_LETTER_CALLBACK_PREFIX,
    COVER_LETTER_SPANISH_CALLBACK_PREFIX,
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
            "allowed_updates": json.dumps(["callback_query"]),
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramBotError(kind="InvalidResponse")
        return [item for item in result if isinstance(item, dict)]

    def answer_callback_query(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def send_text(self, text: str) -> None:
        for chunk in split_text(text):
            self._call("sendMessage", {"chat_id": self._chat_id, "text": chunk})

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
) -> str:
    """Handle one update and return "ignored", "generated", "failed" or "duplicate".

    Updates are handled one at a time, so a second tap on the same button
    arrives after the first letter is done; ``generated`` makes it resend that
    letter instead of paying for a new one.
    """

    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return "ignored"
    message = callback.get("message")
    chat = message.get("chat") if isinstance(message, dict) else None
    origin = chat.get("id") if isinstance(chat, dict) else None
    if origin is None or str(origin) != str(chat_id).strip():
        return "ignored"
    callback_id = str(callback.get("id", ""))
    request = _parse_request(callback.get("data"))
    if request is None:
        _answer(bot, callback_id, "Acción no reconocida")
        return "ignored"
    job_id, language = request
    key = (job_id, language)
    if key in generated:
        _answer(bot, callback_id, "Ya la generé; te la reenvío")
        _send_draft(bot, generated[key])
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
    _send_draft(bot, draft)
    return "generated"


def _answer(bot: TelegramBotClient, callback_id: str, text: str) -> None:
    # Telegram rejects answers to old taps (e.g. made while the bot was off);
    # the request itself is still valid, so carry on.
    try:
        bot.answer_callback_query(callback_id, text)
    except TelegramBotError:
        pass


def _send_draft(bot: TelegramBotClient, draft: CoverLetterDraft) -> None:
    bot.send_text(
        f"✍️ Cover letter — {draft.company} — {draft.title}\n"
        "(Borrador: revísalo antes de usarlo. No se ha enviado a nadie.)\n\n"
        f"{draft.text}"
    )
    for document in (draft.docx_path, draft.pdf_path):
        if document is None:
            continue
        try:
            bot.send_document(document)
        except TelegramBotError:
            pass  # The text is already delivered; a failed upload must not repeat the paid generation.
    if draft.render_error:
        bot.send_text("No se pudieron crear los archivos Word/PDF; el texto del borrador está arriba.")


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
    max_cycles: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda message: print(message, flush=True),
) -> None:
    """Long-poll until interrupted (or ``max_cycles`` polls, used by tests)."""

    offset = load_offset(offset_path)
    generated: dict[tuple[UUID, str], CoverLetterDraft] = {}
    backoff = _BACKOFF_START
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        try:
            updates = bot.get_updates(offset)
            for update in updates:
                try:
                    outcome = handle_update(
                        update, chat_id=chat_id, bot=bot, generate=generate, generated=generated
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
