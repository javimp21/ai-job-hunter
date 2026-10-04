import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import httpx
import pytest

from ai_job_hunter.config import Settings
from ai_job_hunter.cli import main
from ai_job_hunter.services.cover_letters import CoverLetterDraft, CoverLetterError
from ai_job_hunter.services.telegram_bot import (
    TelegramBotClient,
    TelegramBotError,
    handle_update,
    run_bot,
    split_text,
)

TOKEN = "bot-secret-token-123"
CHAT = "4242"


class FakeBot:
    def __init__(self, batches=None):
        self.events: list[tuple[str, str]] = []
        self.batches = list(batches or [])
        self.offsets: list[int | None] = []

    def get_updates(self, offset, timeout_seconds=50):
        self.offsets.append(offset)
        if not self.batches:
            return []
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch

    def answer_callback_query(self, callback_id, text):
        self.events.append(("answer", text))

    def send_text(self, text, reply_markup=None, reply_to=None):
        self.events.append(("send", text))
        self.reply_to = reply_to

    def send_document(self, path, caption=None):
        self.events.append(("doc", Path(path).name))
        return True

    def send_document_group(self, paths, caption=None, reply_to=None):
        self.events.append(("group", ",".join(Path(path).name for path in paths)))
        self.reply_to = reply_to
        self.caption = caption
        return True


def callback(data, *, chat=CHAT, update_id=1):
    return {
        "update_id": update_id,
        "callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": int(chat)}}},
    }


def draft_for(job_id: UUID, text="Hola,\n\nBorrador.") -> CoverLetterDraft:
    return CoverLetterDraft(
        job_id=job_id,
        company="Acme",
        title="Backend Engineer",
        text=text,
        path=Path("x.md"),
        model="m",
        input_tokens=1,
        output_tokens=2,
    )


def test_other_chat_is_ignored_and_generate_not_called():
    bot, calls = FakeBot(), []
    outcome = handle_update(
        callback(f"cl:{uuid4()}", chat="999"),
        chat_id=CHAT,
        bot=bot,
        generate=lambda job_id, language: calls.append((job_id, language)),
        generated={},
    )
    assert outcome == "ignored"
    assert calls == [] and bot.events == []


def test_non_callback_update_is_ignored():
    outcome = handle_update(
        {"update_id": 1, "message": {}}, chat_id=CHAT, bot=FakeBot(), generate=None, generated={}
    )
    assert outcome == "ignored"


@pytest.mark.parametrize("data", ["nope", "cl:not-a-uuid", None, "xx:" + str(uuid4())])
def test_bad_callback_data_is_ignored_with_answer(data):
    bot, calls = FakeBot(), []
    outcome = handle_update(
        callback(data), chat_id=CHAT, bot=bot, generate=lambda job_id, language: calls.append((job_id, language)), generated={}
    )
    assert outcome == "ignored"
    assert calls == []
    assert bot.events == [("answer", "Acción no reconocida")]


def test_valid_callback_answers_generates_then_sends_letter():
    job_id = uuid4()
    bot, generated = FakeBot(), {}
    seen = []

    def generate(value, language):
        seen.append((value, language))
        assert bot.events == [("answer", "Generando cover letter…")]
        return draft_for(value)

    outcome = handle_update(callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=generate, generated=generated)

    assert outcome == "generated"
    assert seen == [(job_id, "auto")]
    assert set(generated) == {(job_id, "auto")}
    kind, text = bot.events[1]
    assert kind == "send"
    assert text.startswith("✍️ Cover letter — Acme — Backend Engineer\n(Borrador:")
    assert text.endswith("Borrador.")


def test_second_tap_resends_existing_letter_without_paying_again():
    job_id = uuid4()
    bot, calls = FakeBot(), []
    outcome = handle_update(
        callback(f"cl:{job_id}"),
        chat_id=CHAT,
        bot=bot,
        generate=lambda value, language: calls.append((value, language)),
        generated={(job_id, "auto"): draft_for(job_id)},
    )
    assert outcome == "duplicate"
    assert calls == []
    assert bot.events[0] == ("answer", "Ya la generé; te la reenvío")
    assert bot.events[1][0] == "send" and bot.events[1][1].endswith("Borrador.")


def test_repeated_taps_in_one_batch_generate_once(tmp_path):
    job_id = uuid4()
    bot = FakeBot([[callback(f"cl:{job_id}", update_id=1), callback(f"cl:{job_id}", update_id=2)]])
    calls = []

    def generate(value, language):
        calls.append((value, language))
        return draft_for(value)

    run_bot(bot, chat_id=CHAT, generate=generate, offset_path=tmp_path / "o.json", max_cycles=1)

    assert calls == [(job_id, "auto")]
    assert [kind for kind, _ in bot.events].count("send") == 2


def test_stale_tap_still_generates_when_answer_is_rejected():
    class StaleBot(FakeBot):
        def answer_callback_query(self, callback_id, text):
            raise TelegramBotError(status_code=400)

    job_id = uuid4()
    bot = StaleBot()
    outcome = handle_update(
        callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=lambda job, language: draft_for(job), generated={}
    )
    assert outcome == "generated"
    assert bot.events[0][0] == "send"


def test_cover_letter_error_and_unexpected_error_are_reported_and_not_cached():
    job_id = uuid4()
    generated: dict = {}

    def known(*_):
        raise CoverLetterError("Job not found.")

    bot = FakeBot()
    assert handle_update(callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=known, generated=generated) == "failed"
    assert bot.events[-1] == ("send", "No se pudo generar la cover letter: Job not found.")
    assert generated == {}

    def unexpected(*_):
        raise ValueError(f"boom {TOKEN}")

    bot = FakeBot()
    assert handle_update(callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=unexpected, generated=generated) == "failed"
    message = bot.events[-1][1]
    assert "ValueError" in message and TOKEN not in message and "boom" not in message
    assert generated == {}


def test_loop_continues_after_failure(tmp_path):
    ok, bad = uuid4(), uuid4()
    bot = FakeBot(
        [[callback(f"cl:{bad}", update_id=5), callback(f"cl:{ok}", update_id=6)]]
    )

    def generate(job_id, language):
        if job_id == bad:
            raise RuntimeError("x")
        return draft_for(job_id)

    run_bot(bot, chat_id=CHAT, generate=generate, offset_path=tmp_path / "o.json", max_cycles=1)

    sends = [text for kind, text in bot.events if kind == "send"]
    assert len(sends) == 2 and "RuntimeError" in sends[0] and sends[1].startswith("✍️")


def test_spanish_callback_generates_in_spanish_and_cache_is_keyed_by_language():
    job_id = uuid4()
    bot, generated, calls = FakeBot(), {}, []

    def generate(value, language):
        calls.append((value, language))
        return draft_for(value)

    def tap(prefix):
        return handle_update(
            callback(f"{prefix}{job_id}"), chat_id=CHAT, bot=bot, generate=generate, generated=generated
        )

    assert tap("cl:") == "generated"
    assert tap("cles:") == "generated"
    assert tap("cles:") == "duplicate"
    assert tap("cl:") == "duplicate"
    assert calls == [(job_id, "auto"), (job_id, "es")]
    assert set(generated) == {(job_id, "auto"), (job_id, "es")}


def test_draft_files_reply_to_the_alert_as_one_group_and_again_on_resend(tmp_path):
    job_id = uuid4()
    docx, pdf = tmp_path / "l.docx", tmp_path / "l.pdf"
    draft = replace(draft_for(job_id), docx_path=docx, pdf_path=pdf)
    bot, generated = FakeBot(), {}
    update = callback(f"cles:{job_id}")
    update["callback_query"]["message"]["message_id"] = 777

    def tap():
        return handle_update(
            update, chat_id=CHAT, bot=bot, generate=lambda value, language: draft, generated=generated,
        )

    assert tap() == "generated" and tap() == "duplicate"
    assert [kind for kind, _ in bot.events] == ["answer", "group", "answer", "group"]
    assert bot.events[1][1] == "l.docx,l.pdf"
    assert bot.reply_to == 777
    assert "Borrador" in bot.caption and draft.text not in bot.caption


def test_render_error_falls_back_to_the_letter_text_as_a_reply():
    job_id = uuid4()
    draft = replace(draft_for(job_id), render_error="Could not render docx (RuntimeError)")
    bot = FakeBot()
    update = callback(f"cl:{job_id}")
    update["callback_query"]["message"]["message_id"] = 42
    handle_update(update, chat_id=CHAT, bot=bot, generate=lambda v, l: draft, generated={})

    assert [kind for kind, _ in bot.events] == ["answer", "send"]
    assert draft.text in bot.events[-1][1] and bot.reply_to == 42


def test_upload_failure_does_not_lose_or_repeat_the_letter(tmp_path):
    class FailingUploads(FakeBot):
        def send_document_group(self, paths, caption=None, reply_to=None):
            raise TelegramBotError(status_code=500)

    job_id = uuid4()
    draft = replace(draft_for(job_id), docx_path=tmp_path / "a.docx")
    bot, generated = FailingUploads(), {}
    outcome = handle_update(
        callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=lambda v, l: draft, generated=generated
    )
    assert outcome == "generated" and (job_id, "auto") in generated


def test_send_document_posts_multipart_with_chat_id_and_skips_large_or_missing_files(tmp_path, monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path.rsplit("/", 1)[-1], request.headers["content-type"], request.read()))
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = TelegramBotClient(TOKEN, CHAT, client=httpx.Client(transport=httpx.MockTransport(handler)))
    document = tmp_path / "letter.pdf"
    document.write_bytes(b"%PDF-1.4 hello")

    assert client.send_document(document, caption="cap") is True
    method, content_type, body = seen[0]
    assert method == "sendDocument" and content_type.startswith("multipart/form-data")
    assert b'name="chat_id"' in body and CHAT.encode() in body and b"cap" in body
    assert b'filename="letter.pdf"' in body and b"%PDF-1.4 hello" in body

    assert client.send_document(tmp_path / "missing.pdf") is False
    monkeypatch.setattr("ai_job_hunter.services.telegram_bot.MAX_DOCUMENT_BYTES", 3)
    assert client.send_document(document) is False
    assert len(seen) == 1


def test_send_document_errors_never_contain_the_token(tmp_path):
    document = tmp_path / "letter.pdf"
    document.write_bytes(b"x")

    def timeout(_request):
        raise httpx.ReadTimeout(f"https://api.telegram.org/bot{TOKEN}/sendDocument")

    def rejected(_request):
        return httpx.Response(413, json={"ok": False, "description": TOKEN})

    for handler in (timeout, rejected):
        client = TelegramBotClient(TOKEN, CHAT, client=httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(TelegramBotError) as error:
            client.send_document(document)
        assert TOKEN not in str(error.value) and TOKEN not in repr(error.value)
        assert error.value.__cause__ is None


def test_long_letter_is_chunked_within_limit():
    text = "\n\n".join("p" * 1500 for _ in range(6)) + "\n\n" + "w" * 9000
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert "".join(chunks).replace("\n", "").count("p") == 6 * 1500
    assert "".join(chunks).count("w") == 9000


def test_offsets_are_persisted_and_resumed(tmp_path):
    path = tmp_path / "nested" / "offset.json"
    first = FakeBot([[callback("bad", update_id=10), callback("bad", update_id=11)]])
    run_bot(first, chat_id=CHAT, generate=None, offset_path=path, max_cycles=1)
    assert json.loads(path.read_text(encoding="utf-8")) == {"offset": 12}
    assert not path.with_name("offset.json.tmp").exists()

    second = FakeBot()
    run_bot(second, chat_id=CHAT, generate=None, offset_path=path, max_cycles=2)
    assert second.offsets == [12, 12]

    fresh = FakeBot()
    run_bot(fresh, chat_id=CHAT, generate=None, offset_path=tmp_path / "missing.json", max_cycles=1)
    assert fresh.offsets == [None]


def test_backoff_doubles_to_cap_and_resets(tmp_path):
    error = TelegramBotError(status_code=502)
    bot = FakeBot([error] * 5 + [[]] + [error])
    sleeps: list[float] = []
    run_bot(bot, chat_id=CHAT, generate=None, offset_path=tmp_path / "o.json", max_cycles=7, sleep=sleeps.append)
    assert sleeps == [5, 10, 20, 40, 60, 5]


def test_httpx_errors_also_back_off(tmp_path):
    bot = FakeBot([httpx.ReadTimeout("x")])
    sleeps: list[float] = []
    run_bot(bot, chat_id=CHAT, generate=None, offset_path=tmp_path / "o.json", max_cycles=2, sleep=sleeps.append)
    assert sleeps == [5]


def test_client_posts_expected_requests_and_chunks_plain_text():
    requests: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path.rsplit("/", 1)[-1], parse_qs(request.read().decode())))
        result = [{"update_id": 1}] if requests[-1][0] == "getUpdates" else True
        return httpx.Response(200, json={"ok": True, "result": result})

    client = TelegramBotClient(TOKEN, CHAT, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.get_updates(7) == [{"update_id": 1}]
    client.answer_callback_query("cb", "hola")
    client.send_text("a" * 5000)

    method, data = requests[0]
    assert method == "getUpdates" and data["offset"] == ["7"]
    assert json.loads(data["allowed_updates"][0]) == ["callback_query", "message"]
    assert requests[1][0] == "answerCallbackQuery" and requests[1][1]["callback_query_id"] == ["cb"]
    sends = requests[2:]
    assert len(sends) == 2 and all(m == "sendMessage" for m, _ in sends)
    assert all("parse_mode" not in d and d["chat_id"] == [CHAT] for _, d in sends)
    assert all(len(d["text"][0]) <= 4000 for _, d in sends)


def test_errors_never_contain_the_token():
    def timeout(_request):
        raise httpx.ReadTimeout(f"https://api.telegram.org/bot{TOKEN}/getUpdates")

    def rejected(_request):
        return httpx.Response(401, json={"ok": False, "description": TOKEN})

    def not_ok(_request):
        return httpx.Response(200, json={"ok": False, "error_code": 409, "description": TOKEN})

    for handler in (timeout, rejected, not_ok):
        client = TelegramBotClient(TOKEN, CHAT, client=httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(TelegramBotError) as error:
            client.get_updates(None)
        assert TOKEN not in str(error.value) and TOKEN not in repr(error.value)
        assert error.value.__cause__ is None


def test_bot_command_requires_telegram_settings(monkeypatch, capsys):
    monkeypatch.setattr("ai_job_hunter.cli.load_candidate_config", lambda _path: object())
    monkeypatch.setattr(
        "ai_job_hunter.cli.get_settings",
        lambda: Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:"),
    )
    monkeypatch.setattr(
        "ai_job_hunter.cli.run_bot",
        lambda *args, **kwargs: pytest.fail("bot must not start without settings"),
    )

    assert main(["bot"]) == 1
    err = capsys.readouterr().err
    assert "TELEGRAM_BOT_TOKEN" in err and "TELEGRAM_CHAT_ID" in err


def test_feedback_buttons_record_state_then_ask_and_store_reason():
    job_id = uuid4()
    recorded = []
    sent = []

    class FeedbackBot(FakeBot):
        def send_text(self, text, reply_markup=None, reply_to=None):
            sent.append((text, reply_markup))

    bot = FeedbackBot()
    outcome = handle_update(
        callback(f"dn:{job_id}"), chat_id=CHAT, bot=bot, generate=draft_for, generated={},
        record_feedback=lambda *args: recorded.append(args),
    )
    assert outcome == "feedback"
    assert recorded == [(job_id, "DISMISSED", None)]
    text, markup = sent[0]
    assert text == "¿Por qué no te interesa?"
    reasons = [button["callback_data"] for row in markup["inline_keyboard"] for button in row]
    assert f"dr:sal:{job_id}" in reasons and all(len(data.encode()) <= 64 for data in reasons)

    handle_update(
        callback(f"dr:sal:{job_id}"), chat_id=CHAT, bot=bot, generate=draft_for, generated={},
        record_feedback=lambda *args: recorded.append(args),
    )
    assert recorded[-1] == (job_id, "DISMISSED", "salary")
    handle_update(
        callback(f"ur:lrn:{job_id}"), chat_id=CHAT, bot=bot, generate=draft_for, generated={},
        record_feedback=lambda *args: recorded.append(args),
    )
    assert recorded[-1] == (job_id, "SAVED", "learning")


def test_bad_feedback_codes_and_failures_are_safe():
    job_id = uuid4()
    bot = FakeBot()
    assert handle_update(
        callback(f"dr:zzz:{job_id}"), chat_id=CHAT, bot=bot, generate=draft_for, generated={},
        record_feedback=lambda *args: None,
    ) == "ignored"

    def boom(*args):
        raise RuntimeError("db down")

    assert handle_update(
        callback(f"up:{job_id}"), chat_id=CHAT, bot=bot, generate=draft_for, generated={}, record_feedback=boom,
    ) == "failed"


def test_send_document_group_posts_one_media_group_replying_to_the_alert(tmp_path):
    docx, pdf = tmp_path / "a.docx", tmp_path / "a.pdf"
    docx.write_bytes(b"docx")
    pdf.write_bytes(b"%PDF")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": []})

    client = TelegramBotClient(TOKEN, CHAT, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.send_document_group([docx, pdf], caption="Borrador", reply_to=9)

    request = requests[0]
    assert request.url.path.endswith("/sendMediaGroup")
    body = request.content.decode("latin-1")
    assert '"attach://file0"' in body and '"attach://file1"' in body
    assert 'name="reply_to_message_id"' in body and "Borrador" in body
    assert not client.send_document_group([tmp_path / "missing.pdf"])
