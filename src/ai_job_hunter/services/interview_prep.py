"""Preparar entrevista: an interview-prep brief for one job the candidate liked.

The brief is written by Claude from the stored posting (and the company website
URL we already hold, which is never fetched) and the candidate's own base CV
(``private/cv/CV_base_<LANG>.md``). It is saved locally as Markdown, Word and
PDF. Nothing is ever sent anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.models import Job
from ai_job_hunter.services.application_pack import DEFAULT_CV_DIR, _slug
from ai_job_hunter.services.cover_letters import (
    COVER_LETTER_MODEL,
    DEFAULT_STYLE_GUIDE_PATH,
    CoverLetterError,
    MessagesClient,
    _FALLBACK_BETA,
    _anthropic_client,
    _as_lines,
    _detect_language,
    _posting_facts,
    _validate_language,
)
from ai_job_hunter.services.cv_documents import parse_cv, render_cv_docx, render_cv_pdf

DEFAULT_INTERVIEW_DIR = Path("data/local/interviews")
_LANGUAGE_INSTRUCTIONS = {
    "es": "Language: write the whole brief in Spanish (natural peninsular Spanish, informal tuteo).",
    "en": "Language: write the whole brief in English.",
}

_SYSTEM_PROMPT = """\
You prepare one candidate for one job interview. You write a practical brief the candidate will read the night before.

Hard rules:
- Facts about the company come ONLY from the job posting text and the company website URL given. You cannot browse; the URL is a pointer, never a source of facts, and you must not infer facts from the domain name. Anything the posting does not say is "no consta" (Spanish) / "not stated" (English). Never invent products, clients, funding, size, stack, culture or news.
- Facts about the candidate come ONLY from the base CV. Never claim, suggest or imply experience, technologies, numbers, employers or achievements that are not in the CV. When a question touches something the CV does not show, say so plainly in the gap section instead of stretching the CV.
- Never state the candidate's years of experience.
- Write in the language requested, plain and direct, no AI-sounding filler.

Output the brief in this exact Markdown subset (only "# ", "## ", "- " lines and plain lines; **bold** allowed; no tables, no "###", no numbered-list syntax, no blank-line-dependent structure):

# <Company> — <Title>: interview brief
## <section: what the company does>
Plain lines. Only what the posting and URL support; otherwise "no consta".
## <section: what the role really involves>
- 4-7 bullets: day-to-day work, stack, responsibilities, seniority signals and red flags read from the posting. Mark inferences as such.
## <section: likely questions (8-12)>
For each question, one line of the form **P1. <question>** followed by exactly three bullets:
- Tipo: technical (tied to the posting's stack) or behavioural
- Experiencia real a usar: which real item from the base CV to answer with, named concretely (employer, project, technology exactly as in the CV); if none fits, say so
- Cómo enfocarla: one or two sentences on what to stress and what to avoid
Use 8-12 questions: roughly two thirds technical and one third behavioural.
## <section: honest gaps>
For each technology or requirement in the posting that the CV does not show: one bullet with the gap, then how to talk about it positively and truthfully (closest real experience, quick learning shown by real facts in the CV, concrete next step). Never pretend the gap does not exist.
## <section: questions for the candidate to ask>
4-5 bullets: good, specific questions that follow from the posting (team, process, stack decisions, onboarding, success in the first months). No questions whose answer is already in the posting.

Translate the section titles and the labels "Tipo", "Experiencia real a usar" and "Cómo enfocarla" into the requested language. Output only the brief.

Candidate style guide (voice for suggested phrasings only; the rules above take precedence):
"""


@dataclass(frozen=True, slots=True)
class InterviewPrep:
    job_id: UUID
    company: str
    title: str
    language: str
    markdown: str
    md_path: Path
    docx_path: Path | None
    pdf_path: Path | None
    render_error: str | None
    apply_url: str | None
    model: str


def prepare_interview(
    session: Session,
    candidate: CandidateConfig,
    job_id: UUID,
    *,
    language: str = "auto",
    cv_dir: Path = DEFAULT_CV_DIR,
    output_dir: Path = DEFAULT_INTERVIEW_DIR,
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
    client: MessagesClient | None = None,
    now: datetime | None = None,
) -> InterviewPrep:
    """Build and save the brief; raises CoverLetterError with a safe message on failure."""

    _validate_language(language)
    job = session.scalar(
        select(Job).options(joinedload(Job.company), selectinload(Job.sources)).where(Job.id == job_id)
    )
    if job is None:
        raise CoverLetterError(f"Unknown job id: {job_id}.")
    posting = _posting_facts(job)
    session.rollback()

    resolved = language if language != "auto" else _detect_language(posting.get("description") or posting["title"])
    base_path = cv_dir / f"CV_base_{resolved.upper()}.md"
    if not base_path.exists():
        raise CoverLetterError(f"Base CV not found at {base_path}.")
    base_cv = base_path.read_text(encoding="utf-8")
    style_guide = style_guide_path.read_text(encoding="utf-8") if style_guide_path.exists() else ""

    request = build_interview_request(posting=posting, base_cv=base_cv, style_guide=style_guide, language=resolved)
    active_client = client or _anthropic_client()
    try:
        response = active_client.beta.messages.create(**request)
    except Exception as error:  # noqa: BLE001 - provider errors may echo request details
        raise CoverLetterError(f"Claude request failed ({type(error).__name__}).") from None
    if getattr(response, "stop_reason", None) == "refusal":
        raise CoverLetterError("Claude declined to write this brief.")
    text = "".join(
        block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise CoverLetterError("Claude returned an empty brief.")

    created = now or datetime.now(UTC)
    model = getattr(response, "model", COVER_LETTER_MODEL)
    folder = output_dir / f"{created:%Y%m%d-%H%M%S}-{_slug(posting['company'])}-{_slug(posting['title'])}"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"entrevista_{resolved.upper()}"
    markdown = text + "\n"
    md_path = folder / f"{stem}.md"
    md_path.write_text(markdown, encoding="utf-8")
    blocks = parse_cv(markdown)
    docx_path = pdf_path = None
    errors: list[str] = []
    try:
        docx_path = render_cv_docx(blocks, folder / f"{stem}.docx")
    except Exception as error:  # noqa: BLE001 - the Markdown brief is still saved
        errors.append(f"docx ({type(error).__name__})")
    try:
        pdf_path = render_cv_pdf(blocks, folder / f"{stem}.pdf", title=f"{posting['company']} — {posting['title']}")
    except Exception as error:  # noqa: BLE001
        errors.append(f"pdf ({type(error).__name__})")
    return InterviewPrep(
        job_id=job_id,
        company=posting["company"],
        title=posting["title"],
        language=resolved,
        markdown=markdown,
        md_path=md_path,
        docx_path=docx_path,
        pdf_path=pdf_path,
        render_error=("Could not render " + ", ".join(errors)) if errors else None,
        apply_url=posting.get("url"),
        model=model,
    )


def build_interview_request(
    *, posting: dict[str, Any], base_cv: str, style_guide: str, language: str
) -> dict[str, Any]:
    """Build the Messages API request; pure so the prompt can be tested offline."""

    instruction = _LANGUAGE_INSTRUCTIONS[language]
    return {
        "model": COVER_LETTER_MODEL,
        "max_tokens": 16_000,
        "system": [{
            "type": "text",
            "text": _SYSTEM_PROMPT + style_guide.strip(),
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{
            "role": "user",
            "content": (
                f"<base_cv>\n{base_cv}\n</base_cv>\n\n"
                f"<job_posting>\n{_as_lines(posting)}\n</job_posting>\n\n"
                f"{instruction}\n\nWrite the interview brief for this job."
            ),
        }],
        "output_config": {"effort": "high"},
        "betas": [_FALLBACK_BETA],
        "fallbacks": "default",
    }
