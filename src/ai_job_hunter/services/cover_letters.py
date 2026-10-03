"""Draft a cover letter for one stored job with Claude; nothing is ever sent.

The letter is built only from verifiable inputs: the stored job posting, the
candidate's configured profile and contact facts, the candidate's own CV, and
the candidate's writing-style guide. The draft is saved locally for human
review. Salary expectations and private contact details are never sent to the
model.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.application_prep.configuration import CandidateApplicationFacts
from ai_job_hunter.application_prep.models import CandidateDocument, CandidateDocumentType
from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.config import get_settings
from ai_job_hunter.models import Job
from ai_job_hunter.services.cover_letter_documents import render_docx, render_pdf

COVER_LETTER_MODEL = "claude-opus-5-5"
LANGUAGES = ("auto", "es", "en")
_LANGUAGE_INSTRUCTIONS = {
    "es": (
        "Language override: write the letter in Spanish (natural peninsular Spanish, informal "
        "tuteo unless the posting is very formal), regardless of the language of the posting."
    ),
    "en": "Language override: write the letter in English, regardless of the language of the posting.",
}
_SPANISH_HINTS = frozenset(
    "el la los las de del que y en un una con por para es me su sus al lo se mi como más nuestro equipo trabajo experiencia".split()
)
_ENGLISH_HINTS = frozenset(
    "the and of to in a is for with that this my your our team work experience i at on as".split()
)
DEFAULT_STYLE_GUIDE_PATH = Path("private/WRITING.md")
DEFAULT_OUTPUT_DIR = Path("data/local/cover-letters")
_MAX_DESCRIPTION_CHARS = 30_000
_MAX_CV_BYTES = 5_000_000
# Server-side fallback when a safety classifier declines (Claude API only).
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_SYSTEM_PROMPT = """\
You write job-application cover letters on behalf of one specific person, in that person's own voice.

Hard rules:
- Use only facts present in the inputs: the job posting, the candidate facts, and the candidate's CV. Never invent experience, projects, numbers, technologies, motivations or company facts. If the posting gives little detail about the company, say less rather than guessing.
- Write in the language of the job posting (Spanish posting -> Spanish letter; otherwise English).
- 180-260 words, 3-5 short paragraphs, plain text. No subject line, no placeholders, no address block, no date.
- Mention one or two concrete things from the posting that genuinely connect to the candidate's background or stated learning interests, and say why in plain words.
- If the posting asks for a technology the candidate lacks, do not hide it and do not apologise at length: one honest sentence pairing the gap with the closest real experience and the intent to learn. Mention years of experience only if the posting explicitly requires more than the candidate has, and then in the same single sentence.
- Motivations must come from the style guide's confirmed situation/motivations section, the CV, or the posting; do not infer new ones.
- Follow the candidate's style guide below exactly; it overrides generic cover-letter conventions. Avoid every phrase it lists as AI-sounding.
- Sign with the sign-off name from the style guide if it gives one, otherwise the candidate's first name.
- Output only the letter text.

Candidate style guide:
"""


class CoverLetterError(RuntimeError):
    """A safe, user-readable failure; never includes credentials or raw provider errors."""


class MessagesClient(Protocol):
    """The part of the Anthropic client used here (lets tests inject a fake)."""

    beta: Any


@dataclass(frozen=True, slots=True)
class CoverLetterDraft:
    job_id: UUID
    company: str
    title: str
    text: str
    path: Path
    model: str
    input_tokens: int | None
    output_tokens: int | None
    language: str = "en"
    docx_path: Path | None = None
    pdf_path: Path | None = None
    render_error: str | None = None


def generate_cover_letter(
    session: Session,
    candidate: CandidateConfig,
    job_id: UUID,
    *,
    application_facts: CandidateApplicationFacts,
    documents: tuple[CandidateDocument, ...] = (),
    style_guide_path: Path = DEFAULT_STYLE_GUIDE_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    client: MessagesClient | None = None,
    now: datetime | None = None,
    language: str = "auto",
    render_documents: bool = True,
) -> CoverLetterDraft:
    _validate_language(language)
    job = session.scalar(
        select(Job)
        .options(joinedload(Job.company), selectinload(Job.sources))
        .where(Job.id == job_id)
    )
    if job is None:
        raise CoverLetterError(f"Unknown job id: {job_id}.")
    posting = _posting_facts(job)
    session.rollback()
    if not style_guide_path.exists():
        raise CoverLetterError(f"Writing style guide not found at {style_guide_path}.")
    style_guide = style_guide_path.read_text(encoding="utf-8")
    cv_pdf = _read_cv(documents)

    request = build_cover_letter_request(
        posting=posting,
        candidate_facts=candidate_facts_for_letter(candidate, application_facts),
        style_guide=style_guide,
        cv_pdf=cv_pdf,
        language=language,
    )
    active_client = client or _anthropic_client()
    try:
        response = active_client.beta.messages.create(**request)
    except Exception as error:  # Provider errors may echo request details; report the type only.
        raise CoverLetterError(f"Claude request failed ({type(error).__name__}).") from None
    if getattr(response, "stop_reason", None) == "refusal":
        raise CoverLetterError("Claude declined to write this letter.")
    text = "".join(
        block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise CoverLetterError("Claude returned an empty letter.")

    created = now or datetime.now(UTC)
    resolved_language = language if language != "auto" else _detect_language(text)
    path = _save_draft(
        output_dir, posting, text, getattr(response, "model", COVER_LETTER_MODEL), created, resolved_language
    )
    usage = getattr(response, "usage", None)
    draft = CoverLetterDraft(
        job_id=job_id,
        company=posting["company"],
        title=posting["title"],
        text=text,
        path=path,
        model=getattr(response, "model", COVER_LETTER_MODEL),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        language=resolved_language,
    )
    if not render_documents:
        return draft
    return _with_documents(draft, application_facts, created.date())


def _with_documents(draft: CoverLetterDraft, applicant: CandidateApplicationFacts, today: date) -> CoverLetterDraft:
    """Render Word and PDF copies; a failure never loses the saved text draft."""

    docx_path: Path | None = None
    pdf_path: Path | None = None
    errors: list[str] = []
    try:
        docx_path = render_docx(draft, applicant, draft.path.with_suffix(".docx"), today=today)
    except Exception as error:  # noqa: BLE001 - report the type only
        errors.append(f"docx ({type(error).__name__})")
    try:
        pdf_path = render_pdf(draft, applicant, draft.path.with_suffix(".pdf"), today=today)
    except Exception as error:  # noqa: BLE001
        errors.append(f"pdf ({type(error).__name__})")
    return replace(
        draft,
        docx_path=docx_path,
        pdf_path=pdf_path,
        render_error=("Could not render " + ", ".join(errors)) if errors else None,
    )


def _validate_language(language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {', '.join(LANGUAGES)}; got {language!r}.")


def _detect_language(text: str) -> str:
    words = re.findall(r"[a-záéíóúñ]+", text.casefold())
    spanish = sum(word in _SPANISH_HINTS for word in words)
    english = sum(word in _ENGLISH_HINTS for word in words)
    return "es" if spanish > english else "en"


def build_cover_letter_request(
    *,
    posting: dict[str, Any],
    candidate_facts: dict[str, Any],
    style_guide: str,
    cv_pdf: bytes | None,
    language: str = "auto",
) -> dict[str, Any]:
    """Build the Messages API request; pure so prompts can be tested offline."""

    _validate_language(language)
    instruction = _LANGUAGE_INSTRUCTIONS.get(language)
    content: list[dict[str, Any]] = []
    if cv_pdf is not None:
        content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(cv_pdf).decode("ascii"),
            },
            "title": "Candidate CV",
        })
    content.append({
        "type": "text",
        "text": (
            "<candidate_facts>\n" + _as_lines(candidate_facts) + "\n</candidate_facts>\n\n"
            "<job_posting>\n" + _as_lines(posting) + "\n</job_posting>\n\n"
            + (f"{instruction}\n\n" if instruction else "")
            + "Write the cover letter for this job."
        ),
    })
    return {
        "model": COVER_LETTER_MODEL,
        "max_tokens": 16_000,
        "system": [{
            "type": "text",
            "text": _SYSTEM_PROMPT + style_guide.strip(),
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": "high"},
        "betas": [_FALLBACK_BETA],
        "fallbacks": "default",
    }


def candidate_facts_for_letter(
    candidate: CandidateConfig,
    application: CandidateApplicationFacts,
) -> dict[str, Any]:
    """Facts the letter may use; excludes salary, email, phone and URLs."""

    profile = candidate.profile
    facts: dict[str, Any] = {
        "first_name": application.first_name,
        "current_role": profile.current_role,
        "current_company": application.current_company,
        "years_of_professional_experience": (
            format(profile.years_of_experience.normalize(), "f")
            if profile.years_of_experience is not None
            else None
        ),
        "current_city": application.current_city,
        "primary_skills": list(profile.primary_skills),
        "secondary_skills": list(profile.secondary_skills),
        "technologies": list(profile.technologies),
        "languages": list(profile.languages),
        "technologies_wants_to_learn": list(candidate.preferences.willing_to_learn_technologies),
    }
    return {key: value for key, value in facts.items() if value not in (None, [], "")}


def _posting_facts(job: Job) -> dict[str, Any]:
    source = max(job.sources, key=lambda item: len(item.source_description or ""), default=None)
    description = (source.source_description if source else None) or job.description or ""
    facts = {
        "company": job.company.name if job.company else "Unknown company",
        "company_website": job.company.website_url if job.company else None,
        "title": (source.source_title if source else None) or job.title,
        "location": (source.source_location if source else None) or job.location,
        "work_mode": source.remote_policy if source else None,
        "description": description[:_MAX_DESCRIPTION_CHARS],
        "url": (source.apply_url or source.canonical_url or source.original_url) if source else None,
    }
    return {key: value for key, value in facts.items() if value}


def _read_cv(documents: tuple[CandidateDocument, ...]) -> bytes | None:
    for document in documents:
        if document.type is not CandidateDocumentType.CV:
            continue
        path = Path(document.local_path)
        if path.suffix.casefold() != ".pdf" or not path.is_file():
            continue
        if path.stat().st_size > _MAX_CV_BYTES:
            raise CoverLetterError("The configured CV PDF is too large to send.")
        return path.read_bytes()
    return None


def _as_lines(values: dict[str, Any]) -> str:
    lines = []
    for key, value in values.items():
        rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def _save_draft(
    output_dir: Path, posting: dict[str, Any], text: str, model: str, created: datetime, language: str
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(f"{posting['company']}-{posting['title']}")[:80]
    path = output_dir / f"{created:%Y%m%d-%H%M%S}-{slug}-{language}.md"
    header = [
        f"# {posting['company']} — {posting['title']}",
        "",
        f"- Generated: {created.isoformat(timespec='seconds')} with {model}",
        f"- Language: {language}",
    ]
    if posting.get("url"):
        header.append(f"- Posting: {posting['url']}")
    header.extend(["- Status: DRAFT — review before using; never sent automatically.", "", "---", ""])
    path.write_text("\n".join(header) + text + "\n", encoding="utf-8")
    return path


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "job"


def _anthropic_client() -> MessagesClient:
    try:
        import anthropic
    except ImportError as error:
        raise CoverLetterError(
            'Cover letters need the Anthropic SDK: pip install -e ".[llm]".'
        ) from error
    key = get_settings().anthropic_api_key
    if key is None or not key.get_secret_value().strip():
        raise CoverLetterError("ANTHROPIC_API_KEY is not configured in .env.")
    return anthropic.Anthropic(api_key=key.get_secret_value().strip())
