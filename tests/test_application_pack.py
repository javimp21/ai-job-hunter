from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from ai_job_hunter.services.application_pack import (
    ANSWERS_MARKER,
    format_answers,
    prepare_application,
    validate_tailored_cv,
)
from ai_job_hunter.services.cover_letters import COVER_LETTER_MODEL
from ai_job_hunter.services.cv_documents import parse_cv, render_cv_docx, render_cv_pdf
from ai_job_hunter.services.notifications import cover_letter_keyboard
from ai_job_hunter.services.telegram_bot import handle_update
from tests.test_cover_letters import _application, _candidate, _job, _style

BASE_CV = """# Alex Example
**Backend Software Engineer | Java | Spring Boot**
Madrid, Spain | alex@example.test | github.com/alex

## PROFESSIONAL SUMMARY
Backend engineer building Java and Spring Boot APIs for a bank.

## EXPERIENCE
**Backend Developer** — Fictional Bank, Madrid — *Sep 2025 – Present*
- Develop REST APIs in Java and Spring Boot integrating message queues (MQ).
- Migrated two complete REST APIs end to end.

## TECHNICAL SKILLS
- **Backend:** Java, Spring Boot, REST APIs
- **Languages & data:** Java, Python, SQL
"""

TAILORED_CV = """# Alex Example
**Backend Software Engineer | Java | Python**
Madrid, Spain | alex@example.test | github.com/alex

## PROFESSIONAL SUMMARY
Backend engineer building REST APIs in Java for a bank, with message queues.

## EXPERIENCE
**Backend Developer** — Fictional Bank, Madrid — *Sep 2025 – Present*
- Migrated two complete REST APIs end to end.
- Develop REST APIs in Java and Spring Boot integrating message queues (MQ).

## TECHNICAL SKILLS
- **Languages & data:** Python, Java, SQL
- **Backend:** REST APIs, Java, Spring Boot
"""


class SequencedMessages:
    def __init__(self, texts):
        self.texts = list(texts)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        text = self.texts.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason="end_turn",
            model=COVER_LETTER_MODEL,
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def _client(*texts):
    messages = SequencedMessages(texts)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_reordering_and_rephrasing_with_base_facts_is_accepted():
    assert validate_tailored_cv(BASE_CV, TAILORED_CV) == []


def test_invented_skill_number_headline_or_changed_fact_lines_are_rejected():
    invented = TAILORED_CV.replace("Python, Java, SQL", "Python, Java, SQL, Kafka")
    numbers = TAILORED_CV.replace("Migrated two complete", "Migrated 12 complete")
    headline = TAILORED_CV.replace("| Java | Python**", "| Java | Kubernetes**")
    dates = TAILORED_CV.replace("Sep 2025 – Present", "Jan 2024 – Present")

    assert any("Kafka" in problem for problem in validate_tailored_cv(BASE_CV, invented))
    assert any("12" in problem for problem in validate_tailored_cv(BASE_CV, numbers))
    assert any("Kubernetes" in problem for problem in validate_tailored_cv(BASE_CV, headline))
    assert validate_tailored_cv(BASE_CV, dates)


def test_cv_renders_to_word_and_pdf(tmp_path):
    blocks = parse_cv(BASE_CV)
    assert ("section", "EXPERIENCE") in blocks and blocks[0] == ("name", "Alex Example")
    assert render_cv_docx(blocks, tmp_path / "cv.docx").stat().st_size > 0
    assert render_cv_pdf(blocks, tmp_path / "cv.pdf").read_bytes().startswith(b"%PDF")


def _cv_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "cv"
    folder.mkdir()
    (folder / "CV_base_EN.md").write_text(BASE_CV, encoding="utf-8")
    return folder


def _prepare(db_session, tmp_path, *responses):
    job = _job(db_session)
    client, messages = _client(*responses)
    pack = prepare_application(
        db_session,
        _candidate(),
        job.id,
        application_facts=_application(),
        language="en",
        cv_dir=_cv_dir(tmp_path),
        output_dir=tmp_path / "packs",
        letter_output_dir=tmp_path / "letters",
        style_guide_path=_style(tmp_path),
        client=client,
    )
    return pack, messages


def test_pack_has_tailored_cv_letter_and_answers(db_session, tmp_path):
    answers = "WHY_COMPANY: You build fintech products.\nWHY_ROLE: It is backend work with Java."
    pack, messages = _prepare(db_session, tmp_path, "Hi,\n\nLetter.\n\nThanks,\nAlex", f"{TAILORED_CV}\n{ANSWERS_MARKER}\n{answers}")

    assert pack.cv_tailored and pack.cv_note is None
    assert pack.cv_pdf.exists() and pack.cv_docx.exists() and pack.letter.text.startswith("Hi")
    assert "You build fintech products." in pack.answers_text
    assert "https://boards.greenhouse.io/acme/jobs/1" in pack.answers_text
    assert (pack.cv_pdf.parent / "CV_EN.md").read_text(encoding="utf-8") == TAILORED_CV
    assert "<base_cv>" in messages.requests[1]["messages"][0]["content"]


def test_invalid_tailoring_falls_back_to_the_base_cv(db_session, tmp_path):
    bad = TAILORED_CV.replace("Python, Java, SQL", "Python, Java, SQL, Kubernetes")
    pack, _ = _prepare(db_session, tmp_path, "Hi,\n\nLetter.\n\nThanks,\nAlex", f"{bad}\n{ANSWERS_MARKER}\nWHY_COMPANY: x")

    assert not pack.cv_tailored and "Kubernetes" in pack.cv_note
    assert (pack.cv_pdf.parent / "CV_EN.md").read_text(encoding="utf-8") == BASE_CV


def test_factual_answers_come_from_settings_not_the_model():
    facts = _application().model_copy(update={"notice_period": "15 días", "work_authorization_response": "Ciudadano UE"})
    text = format_answers("es", {}, application_facts=facts, candidate=_candidate(), salary="45.000–55.000 EUR", apply_url=None)

    assert "15 días" in text and "Ciudadano UE" in text
    assert "45.000–55.000 EUR" in text and "(completa tú)" in text


class FakeBot:
    def __init__(self):
        self.texts, self.groups, self.answers = [], [], []

    def answer_callback_query(self, callback_id, text):
        self.answers.append(text)

    def send_text(self, text, reply_markup=None, reply_to=None):
        self.texts.append((text, reply_to))

    def send_document_group(self, paths, caption=None, reply_to=None):
        self.groups.append((list(paths), caption, reply_to))
        return True


def _update(data, message_id=77):
    return {"callback_query": {"id": "cb", "data": data, "message": {"message_id": message_id, "chat": {"id": 42}}}}


def test_alert_button_prepares_once_and_replies_with_files_and_answers(tmp_path):
    job_id = uuid4()
    letter = SimpleNamespace(docx_path=tmp_path / "l.docx", pdf_path=tmp_path / "l.pdf", text="Letter")
    pack = SimpleNamespace(
        company="Acme", title="Backend", cv_tailored=True, cv_note=None, cv_docx=tmp_path / "c.docx",
        cv_pdf=tmp_path / "c.pdf", letter=letter, answers_text="**Why?**\nBecause.",
    )
    calls = []
    bot, prepared = FakeBot(), {}

    def prepare(requested):
        calls.append(requested)
        return pack

    first = handle_update(_update(f"pc:{job_id}"), chat_id="42", bot=bot, generate=None, generated={}, prepare=prepare, prepared=prepared)
    again = handle_update(_update(f"pc:{job_id}"), chat_id="42", bot=bot, generate=None, generated={}, prepare=prepare, prepared=prepared)

    assert (first, again) == ("generated", "duplicate") and calls == [job_id]
    files, caption, reply_to = bot.groups[0]
    assert len(files) == 4 and reply_to == 77 and "no se ha enviado nada" in caption
    assert bot.texts[0][0].startswith("📋 Respuestas") and "**" not in bot.texts[0][0]


def test_every_alert_offers_the_application_pack_button():
    job_id = uuid4()
    buttons = [button["callback_data"] for row in cover_letter_keyboard(job_id)["inline_keyboard"] for button in row]
    assert f"pc:{job_id}" in buttons
