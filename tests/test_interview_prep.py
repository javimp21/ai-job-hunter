from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_job_hunter.services.cover_letters import COVER_LETTER_MODEL, CoverLetterError
from ai_job_hunter.services.interview_prep import prepare_interview
from ai_job_hunter.services.notifications import feedback_reason_keyboard
from ai_job_hunter.services.telegram_bot import handle_update
from tests.test_application_pack import BASE_CV, FakeBot, _update
from tests.test_cover_letters import _candidate, _job, _style

BRIEF = """# Acme — Backend Engineer: interview brief
## What the company does
Not stated beyond the posting: Java services with Kafka.
## What the role involves
- Build Java services with Kafka.
## Likely questions
**P1. How do you design a REST API?**
- Type: technical
- Real experience to use: Fictional Bank REST APIs in Java and Spring Boot
- How to approach it: concrete example
## Honest gaps
- Kafka is not in the CV: mention the message queues (MQ) work and the plan to learn it.
## Questions to ask
- How is the team organised?
"""


class FakeMessages:
    def __init__(self, text=BRIEF, error=None):
        self.text, self.error, self.requests = text, error, []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            stop_reason="end_turn",
            model=COVER_LETTER_MODEL,
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def _cv_dir(tmp_path: Path, language="EN") -> Path:
    folder = tmp_path / "cv"
    folder.mkdir(exist_ok=True)
    (folder / f"CV_base_{language}.md").write_text(BASE_CV, encoding="utf-8")
    return folder


def _prepare(db_session, tmp_path, messages, **overrides):
    job = overrides.pop("job", None) or _job(db_session)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return prepare_interview(
        db_session,
        _candidate(),
        job.id,
        language=overrides.pop("language", "en"),
        cv_dir=overrides.pop("cv_dir", None) or _cv_dir(tmp_path),
        output_dir=tmp_path / "interviews",
        style_guide_path=_style(tmp_path),
        client=client,
        **overrides,
    )


def test_brief_is_saved_as_markdown_word_and_pdf(db_session, tmp_path):
    messages = FakeMessages()
    brief = _prepare(db_session, tmp_path, messages)

    assert brief.language == "en" and brief.company == "Acme"
    assert brief.md_path.read_text(encoding="utf-8") == BRIEF
    assert brief.docx_path.stat().st_size > 0 and brief.pdf_path.read_bytes().startswith(b"%PDF")
    assert brief.render_error is None
    assert brief.md_path.parent.parent == tmp_path / "interviews"
    assert "acme-backend-engineer" in brief.md_path.parent.name


def test_request_uses_cover_letter_shape_and_grounds_only_on_cv_and_posting(db_session, tmp_path):
    messages = FakeMessages()
    _prepare(db_session, tmp_path, messages)

    request = messages.requests[0]
    assert request["model"] == COVER_LETTER_MODEL and request["output_config"] == {"effort": "high"}
    assert request["fallbacks"] == "default" and request["betas"]
    system = request["system"][0]
    assert system["cache_control"] == {"type": "ephemeral"} and "Plain and honest" in system["text"]
    assert "no consta" in system["text"] and "Never state the candidate's years" in system["text"]
    content = request["messages"][0]["content"]
    assert "<base_cv>" in content and "Fictional Bank" in content
    assert "company_website: https://acme.example.test" in content
    assert "Build Java services with Kafka" in content
    assert "in English" in content
    # Private candidate facts (salary, contact) are never sent.
    for secret in ("99999", "26000", "alex@example.test"):
        assert secret not in content.replace(BASE_CV, "")


def test_auto_language_follows_the_posting_and_picks_the_matching_base_cv(db_session, tmp_path):
    messages = FakeMessages()
    with pytest.raises(CoverLetterError, match="CV_base_EN.md"):
        _prepare(db_session, tmp_path, messages, language="auto", cv_dir=_cv_dir(tmp_path, "ES"))
    assert messages.requests == []


def test_missing_base_cv_unknown_job_and_provider_errors_are_safe(db_session, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    job = _job(db_session)
    with pytest.raises(CoverLetterError, match="Base CV not found"):
        _prepare(db_session, tmp_path, FakeMessages(), cv_dir=empty, job=job)
    with pytest.raises(CoverLetterError, match=r"Claude request failed \(RuntimeError\)") as failure:
        _prepare(db_session, tmp_path, FakeMessages(error=RuntimeError("sk-secret-key")), job=job)
    assert "sk-secret" not in str(failure.value)
    with pytest.raises(CoverLetterError, match="empty brief"):
        _prepare(db_session, tmp_path, FakeMessages(text="  "), job=job)
    with pytest.raises(CoverLetterError, match="Unknown job id"):
        prepare_interview(db_session, _candidate(), uuid4(), cv_dir=empty, client=SimpleNamespace())


def test_saved_reason_keyboard_offers_interview_prep_and_dismissed_does_not():
    job_id = uuid4()

    def callbacks(saved):
        rows = feedback_reason_keyboard(job_id, saved=saved)["inline_keyboard"]
        return [button["callback_data"] for row in rows for button in row]

    assert f"ip:{job_id}" in callbacks(True)
    assert not any(data.startswith("ip:") for data in callbacks(False))
    assert all(len(data.encode()) <= 64 for data in callbacks(True))


def _brief(tmp_path, **overrides):
    values = dict(
        company="Acme", title="Backend", markdown="# Brief\n**P1. Q**", render_error=None,
        docx_path=tmp_path / "b.docx", pdf_path=tmp_path / "b.pdf",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_button_prepares_once_replies_to_the_alert_and_resends_on_second_tap(tmp_path):
    job_id, calls, bot, cache = uuid4(), [], FakeBot(), {}

    def prepare(requested):
        calls.append(requested)
        return _brief(tmp_path)

    kwargs = dict(chat_id="42", bot=bot, generate=None, generated={}, prepare_interview=prepare, interviews=cache)
    first = handle_update(_update(f"ip:{job_id}"), **kwargs)
    again = handle_update(_update(f"ip:{job_id}"), **kwargs)

    assert (first, again) == ("generated", "duplicate") and calls == [job_id]
    assert len(bot.groups) == 2
    files, caption, reply_to = bot.groups[0]
    assert [path.name for path in files] == ["b.docx", "b.pdf"] and reply_to == 77
    assert "no se ha enviado nada" in caption and bot.texts == []


def test_failures_and_missing_handler_never_crash_the_bot(tmp_path):
    job_id, bot = uuid4(), FakeBot()

    def failing(_):
        raise CoverLetterError("sin CV base")

    def crashing(_):
        raise ValueError("boom")

    base = dict(chat_id="42", bot=bot, generate=None, generated={})
    assert handle_update(_update(f"ip:{job_id}"), **base) == "ignored"
    assert handle_update(_update(f"ip:{job_id}"), prepare_interview=failing, interviews={}, **base) == "failed"
    assert handle_update(_update(f"ip:{job_id}"), prepare_interview=crashing, interviews={}, **base) == "failed"
    assert handle_update(_update("ip:not-a-uuid"), prepare_interview=failing, **base) == "ignored"
    assert "sin CV base" in bot.texts[0][0] and "ValueError" in bot.texts[1][0]
    assert "boom" not in bot.texts[1][0] and all(reply_to == 77 for _, reply_to in bot.texts)


def test_unrenderable_brief_falls_back_to_text_as_a_reply(tmp_path):
    bot = FakeBot()
    handle_update(
        _update(f"ip:{uuid4()}"), chat_id="42", bot=bot, generate=None, generated={},
        prepare_interview=lambda _: _brief(tmp_path, render_error="Could not render pdf"), interviews={},
    )

    assert bot.groups == [] and bot.texts[0][1] == 77
    assert "P1. Q" in bot.texts[0][0] and "**" not in bot.texts[0][0]
