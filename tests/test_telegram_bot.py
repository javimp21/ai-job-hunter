import json
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

    def send_text(self, text):
        self.events.append(("send", text))


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
        generate=lambda job_id: calls.append(job_id),
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
        callback(data), chat_id=CHAT, bot=bot, generate=lambda job_id: calls.append(job_id), generated={}
    )
    assert outcome == "ignored"
    assert calls == []
    assert bot.events == [("answer", "Acción no reconocida")]


def test_valid_callback_answers_generates_then_sends_letter():
    job_id = uuid4()
    bot, generated = FakeBot(), {}
    seen = []

    def generate(value):
        seen.append(value)
        assert bot.events == [("answer", "Generando cover letter…")]
        return draft_for(value)

    outcome = handle_update(callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=generate, generated=generated)

    assert outcome == "generated"
    assert seen == [job_id]
    assert set(generated) == {job_id}
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
        generate=lambda value: calls.append(value),
        generated={job_id: draft_for(job_id)},
    )
    assert outcome == "duplicate"
    assert calls == []
    assert bot.events[0] == ("answer", "Ya la generé; te la reenvío")
    assert bot.events[1][0] == "send" and bot.events[1][1].endswith("Borrador.")


def test_repeated_taps_in_one_batch_generate_once(tmp_path):
    job_id = uuid4()
    bot = FakeBot([[callback(f"cl:{job_id}", update_id=1), callback(f"cl:{job_id}", update_id=2)]])
    calls = []

    def generate(value):
        calls.append(value)
        return draft_for(value)

    run_bot(bot, chat_id=CHAT, generate=generate, offset_path=tmp_path / "o.json", max_cycles=1)

    assert calls == [job_id]
    assert [kind for kind, _ in bot.events].count("send") == 2


def test_stale_tap_still_generates_when_answer_is_rejected():
    class StaleBot(FakeBot):
        def answer_callback_query(self, callback_id, text):
            raise TelegramBotError(status_code=400)

    job_id = uuid4()
    bot = StaleBot()
    outcome = handle_update(
        callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=draft_for, generated={}
    )
    assert outcome == "generated"
    assert bot.events[0][0] == "send"


def test_cover_letter_error_and_unexpected_error_are_reported_and_not_cached():
    job_id = uuid4()
    generated: dict = {}

    def known(_):
        raise CoverLetterError("Job not found.")

    bot = FakeBot()
    assert handle_update(callback(f"cl:{job_id}"), chat_id=CHAT, bot=bot, generate=known, generated=generated) == "failed"
    assert bot.events[-1] == ("send", "No se pudo generar la cover letter: Job not found.")
    assert generated == {}

    def unexpected(_):
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

    def generate(job_id):
        if job_id == bad:
            raise RuntimeError("x")
        return draft_for(job_id)

    run_bot(bot, chat_id=CHAT, generate=generate, offset_path=tmp_path / "o.json", max_cycles=1)

    sends = [text for kind, text in bot.events if kind == "send"]
    assert len(sends) == 2 and "RuntimeError" in sends[0] and sends[1].startswith("✍️")


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
    assert json.loads(data["allowed_updates"][0]) == ["callback_query"]
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
