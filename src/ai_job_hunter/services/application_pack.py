"""Preparar candidatura: a tailored CV, the cover letter and form answers for one job.

Nothing is ever submitted. The CV is tailored by Claude from the candidate's
own base CV (``private/cv/CV_base_<LANG>.md``) under strict rules, and a
validator rejects any tailored CV that adds a technology, number or section
that is not in the base CV; the base CV is used instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.application_prep.configuration import CandidateApplicationFacts
from ai_job_hunter.application_prep.models import CandidateDocument
from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.models import Job
from ai_job_hunter.services.cover_letters import (
    COVER_LETTER_MODEL,
    DEFAULT_OUTPUT_DIR as DEFAULT_LETTER_DIR,
    DEFAULT_STYLE_GUIDE_PATH,
    CoverLetterDraft,
    CoverLetterError,
    MessagesClient,
    _FALLBACK_BETA,
    _anthropic_client,
    _posting_facts,
    generate_cover_letter,
)
from ai_job_hunter.services.cv_documents import parse_cv, render_cv_docx, render_cv_pdf

DEFAULT_CV_DIR = Path("private/cv")
DEFAULT_PACK_DIR = Path("data/local/applications")
ANSWERS_MARKER = "=====ANSWERS====="
_NUMBER = re.compile(r"\d+")

_TAILOR_PROMPT = """\
You tailor one candidate's CV to one job posting, in the candidate's own voice.

Output the tailored CV in exactly the same Markdown structure as the base CV
(same "# " name line, same "## " sections in the same order, "- " bullets,
**bold** and *italic* exactly as used there), then a line containing only
=====ANSWERS=====, then the two answers described below. Output nothing else.

Hard rules for the CV:
- Use only facts present in the base CV. Never add technologies, tools,
  employers, clients, dates, numbers, certifications, projects or claims.
- Keep the name, contact line, every date, the education and the
  certifications lines exactly as they are.
- You may: rewrite the headline (the bold line under the name) to target the
  role using only technologies the base CV lists; rewrite the summary (at most
  3 sentences) to emphasise the base CV's most relevant real experience for
  this posting; reorder bullets inside a job by relevance; lightly rephrase a
  bullet with the posting's vocabulary only where it describes the same real
  work; reorder skill lines and the items inside them by relevance.
- Never state years of experience. Never mention anything the candidate lacks.
- Keep the same language as the base CV and about the same length (one page).

Answers (same language as the base CV, plain text, the candidate's voice from
the style guide, no AI-sounding phrases):
WHY_COMPANY: 2-3 sentences on why this company, using general verifiable
aspects (sector, product and users, technologies, team, culture) from the
posting, never narrow internal details.
WHY_ROLE: 2-3 sentences on why this role fits, tied to real experience in the
base CV.

Candidate style guide (voice only; the CV rules above take precedence):
"""


@dataclass(frozen=True, slots=True)
class ApplicationPack:
    job_id: UUID
    company: str
    title: str
    language: str
    letter: CoverLetterDraft
    cv_docx: Path | None
    cv_pdf: Path | None
    cv_tailored: bool
    cv_note: str | None
    answers_text: str
    answers_path: Path
    apply_url: str | None


def prepare_application(
    session: Session,
    candidate: CandidateConfig,
    job_id: UUID,
    *,
    application_facts: CandidateApplicationFacts,
    documents: tuple[CandidateDocument, ...] = (),
    language: str = "auto",
    cv_dir: Path = DEFAULT_CV_DIR,
    output_dir: Path = DEFAULT_PACK_DIR,
    letter_output_dir: Path = DEFAULT_LETTER_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
    client: MessagesClient | None = None,
    now: datetime | None = None,
) -> ApplicationPack:
    """Build the pack; the letter step raises CoverLetterError on failure, the CV step degrades to the base CV."""

    active_client = client or _anthropic_client()
    letter = generate_cover_letter(
        session,
        candidate,
        job_id,
        application_facts=application_facts,
        documents=documents,
        style_guide_path=style_guide_path,
        output_dir=letter_output_dir,
        client=active_client,
        now=now,
        language=language,
    )
    job = session.scalar(
        select(Job).options(joinedload(Job.company), selectinload(Job.sources)).where(Job.id == job_id)
    )
    if job is None:
        raise CoverLetterError(f"Unknown job id: {job_id}.")
    posting = _posting_facts(job)
    salary = _posting_salary(job)
    session.rollback()

    base_path = cv_dir / f"CV_base_{letter.language.upper()}.md"
    if not base_path.exists():
        raise CoverLetterError(f"Base CV not found at {base_path}.")
    base_cv = base_path.read_text(encoding="utf-8")
    style_guide = style_guide_path.read_text(encoding="utf-8") if style_guide_path.exists() else ""

    cv_text, answers, note = base_cv, {}, None
    try:
        tailored, answers = _tailor(active_client, base_cv, posting, style_guide)
        problems = validate_tailored_cv(base_cv, tailored)
        if problems:
            note = "CV base (la versión adaptada se descartó: " + "; ".join(problems[:3]) + ")"
        else:
            cv_text = tailored
    except CoverLetterError as error:
        note = f"CV base (no se pudo adaptar: {error})"

    created = now or datetime.now(UTC)
    folder = output_dir / f"{created:%Y%m%d-%H%M%S}-{_slug(posting['company'])}-{_slug(posting['title'])}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"CV_{letter.language.upper()}.md").write_text(cv_text, encoding="utf-8")
    blocks = parse_cv(cv_text)
    cv_docx = cv_pdf = None
    try:
        cv_docx = render_cv_docx(blocks, folder / f"CV_{letter.language.upper()}.docx")
        cv_pdf = render_cv_pdf(blocks, folder / f"CV_{letter.language.upper()}.pdf", title=f"CV — {posting['title']}")
    except Exception as error:  # noqa: BLE001 - the text CV is still saved
        note = (note + "; " if note else "") + f"no se pudo generar Word/PDF ({type(error).__name__})"

    answers_text = format_answers(
        letter.language,
        answers,
        application_facts=application_facts,
        candidate=candidate,
        salary=salary,
        apply_url=posting.get("url"),
    )
    answers_path = folder / "respuestas.md"
    answers_path.write_text(answers_text, encoding="utf-8")
    return ApplicationPack(
        job_id=job_id,
        company=posting["company"],
        title=posting["title"],
        language=letter.language,
        letter=letter,
        cv_docx=cv_docx,
        cv_pdf=cv_pdf,
        cv_tailored=note is None,
        cv_note=note,
        answers_text=answers_text,
        answers_path=answers_path,
        apply_url=posting.get("url"),
    )


def _tailor(client: MessagesClient, base_cv: str, posting: dict[str, Any], style_guide: str) -> tuple[str, dict[str, str]]:
    posting_text = "\n".join(f"{key}: {value}" for key, value in posting.items())
    request = {
        "model": COVER_LETTER_MODEL,
        "max_tokens": 16_000,
        "system": [{"type": "text", "text": _TAILOR_PROMPT + style_guide.strip(), "cache_control": {"type": "ephemeral"}}],
        "messages": [{
            "role": "user",
            "content": f"<base_cv>\n{base_cv}\n</base_cv>\n\n<job_posting>\n{posting_text}\n</job_posting>\n\n"
            "Tailor the CV and write the answers.",
        }],
        "output_config": {"effort": "high"},
        "betas": [_FALLBACK_BETA],
        "fallbacks": "default",
    }
    try:
        response = client.beta.messages.create(**request)
    except Exception as error:  # noqa: BLE001 - provider errors may echo request details
        raise CoverLetterError(f"Claude request failed ({type(error).__name__})") from None
    if getattr(response, "stop_reason", None) == "refusal":
        raise CoverLetterError("Claude declined")
    text = "".join(
        block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"
    ).strip()
    cv, marker, rest = text.partition(ANSWERS_MARKER)
    if not marker or not cv.strip():
        raise CoverLetterError("unexpected response format")
    return cv.strip() + "\n", _parse_answers(rest)


def _parse_answers(text: str) -> dict[str, str]:
    answers: dict[str, str] = {}
    for key in ("WHY_COMPANY", "WHY_ROLE"):
        match = re.search(rf"{key}:\s*(.+?)(?=\n[A-Z_]+:|\Z)", text, re.DOTALL)
        if match and match.group(1).strip():
            answers[key] = " ".join(match.group(1).split())
    return answers


def validate_tailored_cv(base: str, tailored: str) -> list[str]:
    """Reasons to reject a tailored CV; empty when it only reuses base facts."""

    problems: list[str] = []
    base_blocks, new_blocks = parse_cv(base), parse_cv(tailored)
    if [text for kind, text in base_blocks if kind == "section"] != [text for kind, text in new_blocks if kind == "section"]:
        problems.append("secciones distintas")
    if [text for kind, text in base_blocks if kind == "name"] != [text for kind, text in new_blocks if kind == "name"]:
        problems.append("nombre cambiado")
    base_numbers = set(_NUMBER.findall(base))
    invented_numbers = sorted(set(_NUMBER.findall(tailored)) - base_numbers)
    if invented_numbers:
        problems.append("números nuevos: " + ", ".join(invented_numbers[:5]))
    base_folded = base.casefold()
    for kind, text in new_blocks:
        if kind != "bullet" or not text.startswith("**") or ":**" not in text:
            continue
        items = text.split(":**", 1)[1]
        for item in (part.strip(" .") for part in items.split(",")):
            if item and item.casefold() not in base_folded:
                problems.append(f"competencia nueva: {item}")
    for kind, text in new_blocks:
        if kind == "text" and text.startswith("**") and text.endswith("**") and "|" in text:
            for item in (part.strip(" *") for part in text.split("|")[1:]):
                if item and item.casefold() not in base_folded:
                    problems.append(f"titular con dato nuevo: {item}")
    new_text_lines = {text for kind, text in new_blocks if kind == "text"}
    for kind, text in base_blocks:
        # Contact, job/company/date, education and certification lines are fixed facts.
        headline = text.startswith("**") and text.endswith("**")  # may be retargeted
        if kind == "text" and not headline and ("|" in text or "—" in text) and text not in new_text_lines:
            problems.append("línea de datos modificada")
            break
    return problems


def format_answers(
    language: str,
    answers: dict[str, str],
    *,
    application_facts: CandidateApplicationFacts,
    candidate: CandidateConfig,
    salary: str | None,
    apply_url: str | None,
) -> str:
    """Form answers: motivation from Claude, everything factual from the candidate's own settings."""

    spanish = language == "es"
    missing = "(completa tú)" if spanish else "(fill in)"
    preferences = candidate.preferences
    target = (
        f"{preferences.target_salary:,.0f} {preferences.salary_currency}".replace(",", ".")
        if getattr(preferences, "target_salary", None) else None
    )
    salary_line = (target or missing) + (f" · la oferta publica {salary}" if salary and spanish else f" · posting says {salary}" if salary else "")
    rows = [
        ("¿Por qué esta empresa?" if spanish else "Why this company?", answers.get("WHY_COMPANY") or missing),
        ("¿Por qué este puesto?" if spanish else "Why this role?", answers.get("WHY_ROLE") or missing),
        ("Disponibilidad / preaviso" if spanish else "Notice period", application_facts.notice_period or missing),
        ("Permiso de trabajo" if spanish else "Work authorization", application_facts.work_authorization_response or missing),
        ("Reubicación" if spanish else "Relocation", application_facts.relocation_response or missing),
        ("Expectativa salarial (tu objetivo)" if spanish else "Salary expectation (your target)", salary_line),
    ]
    lines = [f"**{question}**\n{answer}" for question, answer in rows]
    if apply_url:
        lines.append(("**Enlace para aplicar**\n" if spanish else "**Apply here**\n") + apply_url)
    return "\n\n".join(lines) + "\n"


def _posting_salary(job: Any) -> str | None:
    for source in job.sources:
        low, high, currency = source.salary_min, source.salary_max, source.salary_currency
        if low or high:
            def fmt(value: Any) -> str:
                return f"{float(value):,.0f}".replace(",", ".")
            span = f"{fmt(low)}–{fmt(high)}" if low and high else fmt(low or high)
            return f"{span} {currency or ''}".strip()
    return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:40] or "job"
