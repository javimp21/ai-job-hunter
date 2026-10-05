"""Claude-written outreach drafts, connection notes and follow-ups; nothing is ever sent.

Requests follow the style of ``services/cover_letters.py`` (same model, system
prompt cached, same fallback beta, same safe error reporting). Every text is
built only from the candidate's own base CV, their writing style guide and the
public facts supplied about the company/person, and is then checked in code:
no placeholders, no technology or number that is in none of the inputs, the
LinkedIn note limit (300 characters) and per-channel length rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_job_hunter.candidates.technologies import extract_job_technologies
from ai_job_hunter.company_hunter.ranking import CompanyStage
from ai_job_hunter.services.cover_letters import (
    COVER_LETTER_MODEL,
    DEFAULT_STYLE_GUIDE_PATH,
    CoverLetterError,
    MessagesClient,
    _FALLBACK_BETA,
    _anthropic_client,
    _detect_language,
)

DEFAULT_CV_DIR = Path("private/cv")
LINKEDIN_NOTE_LIMIT = 300
LINKEDIN_DM_LIMIT = 300
EMAIL_WORD_LIMITS = {
    CompanyStage.EARLY_STAGE: 110,
    CompanyStage.MID_SIZE: 170,
    CompanyStage.UNKNOWN: 110,
}
MAX_POST_CHARS = 4000
_MAX_ATTEMPTS = 3
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,60}\]|\{\{|\}\}|<[A-Za-z ]{2,30}>")
_NUMBER = re.compile(r"\d+")
_LANGUAGE_NAMES = {"es": "Spanish (natural peninsular Spanish, informal tuteo)", "en": "English"}


class HunterWritingError(CoverLetterError):
    """A safe, user-readable failure while writing outreach text."""


# --------------------------------------------------------------------------------------
# Inputs


@dataclass(frozen=True, slots=True)
class PersonFacts:
    name: str
    role: str | None
    quote: str | None = None  # the public text that supports the contact
    topic: str | None = None  # a public article/talk of theirs, when found
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class CompanyFacts:
    name: str
    website: str | None
    stage: CompanyStage
    description: str | None
    stack_terms: tuple[str, ...]
    posting_titles: tuple[str, ...]
    fit_reasons: tuple[str, ...]
    unknowns: tuple[str, ...]

    def as_text(self) -> str:
        lines = [f"name: {self.name}"]
        if self.website:
            lines.append(f"website: {self.website}")
        lines.append(f"stage: {self.stage.value} (UNKNOWN means we do not know their size; do not state one)")
        if self.description:
            lines.append(f"description: {self.description[:1500]}")
        if self.stack_terms:
            lines.append("technologies seen in their past job postings: " + ", ".join(self.stack_terms))
        if self.posting_titles:
            lines.append("roles they have posted before: " + "; ".join(self.posting_titles[:6]))
        if self.fit_reasons:
            lines.append("why they fit (from our own evidence): " + "; ".join(self.fit_reasons))
        if self.unknowns:
            lines.append("unknown facts (never guess these): " + ", ".join(self.unknowns))
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class CompanyDrafts:
    language: str
    stage: CompanyStage
    overlap: str
    email_subject: str
    email_body: str
    linkedin_dm: str


# --------------------------------------------------------------------------------------
# Files


def load_base_cv(language: str, cv_dir: Path = DEFAULT_CV_DIR) -> str:
    """The candidate's base CV; falls back to the other language's CV (same facts)."""

    for code in (language, "es" if language == "en" else "en"):
        path = cv_dir / f"CV_base_{code.upper()}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise HunterWritingError(f"Base CV not found at {cv_dir}/CV_base_<LANG>.md; nothing can be written without it.")


def load_style_guide(path: Path = DEFAULT_STYLE_GUIDE_PATH) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def resolve_language(requested: str, *texts: str | None, default: str = "en") -> str:
    if requested in {"es", "en"}:
        return requested
    sample = " ".join(text for text in texts if text)
    return _detect_language(sample) if sample.strip() else default


# --------------------------------------------------------------------------------------
# Prompts

_COMMON_RULES = """\
You write short outreach text on behalf of one specific person, in that person's own voice.

Hard rules:
- Use only facts present in the inputs: the candidate's base CV, the company facts and the person facts. Never invent experience, projects, numbers, technologies, motivations, mutual contacts or company facts. If the company facts are thin, say less rather than guessing.
- Never claim anything about the candidate that is not in the base CV. Never state their years of experience. Never volunteer gaps.
- Never address anyone by a made-up name, never include placeholders, brackets, links or email addresses, and never promise anything.
- Do not flatter. Be specific and verifiable: name the company's real product/technology and the one real thing from the CV that connects to it.
- Follow the candidate's style guide below exactly; it overrides generic conventions. Avoid every phrase it lists as AI-sounding.
"""

_DRAFT_RULES = """\
This is cold outreach to a company that may have no matching open role. Produce two variants.

Channel rules:
- Email, early-stage startup (stage EARLY_STAGE or UNKNOWN): no essay. Research-based opening about the company, then the single best overlap between their work and the candidate's real experience. Short bullets (at most 3) that read in 20-30 seconds. No template-sounding phrases. Under {early_words} words.
- Email, mid-size team (stage MID_SIZE): exactly 3 short pointers about the candidate (real, from the CV) and 1 point about the company. Under {mid_words} words.
- LinkedIn DM: very casual, a ONE-LINE first message (single line, no line breaks, at most {dm_limit} characters), no full pitch, just a hook and an open door.

Output only a JSON object with these string keys, nothing else:
"overlap": one sentence naming the single best overlap you used (for the candidate's review),
"email_subject": a short plain subject,
"email_body": the email text (use the candidate's sign-off from the style guide, otherwise their first name),
"linkedin_dm": the one-line DM.
Language: {language}.
"""

_NOTE_RULES = """\
Write a LinkedIn connection-request note. Hard limit: {limit} characters including spaces (it is rejected above that). Casual, one or two short sentences, in {language}. Mention something specific and verifiable: their company/product, their team's technology, or the public talk/article of theirs given in the person facts. No generic flattery ("I admire your impressive career"), no pitch, no ask for a job, nothing that is not in the base CV. Output only the note text.
"""

_POST_NOTE_RULES = """\
Write a LinkedIn connection-request note grounded in a LinkedIn post of this person that the candidate pasted. Hard limit: {limit} characters including spaces. Casual, one or two short sentences, in {language}. Refer to one concrete idea from the post, truthfully; do not misquote it. No generic flattery, no pitch, nothing that is not in the base CV. Output only the note text.
"""

_FOLLOW_UP_RULES = """\
The person just accepted the candidate's LinkedIn connection request. Write the candidate's first direct message: very casual, ONE line (no line breaks), at most {limit} characters, in {language}. Thank them briefly, add one specific and verifiable hook (their company/product, team technology, or their public talk/article), and leave an open door; no full pitch, no job ask, nothing that is not in the base CV. Output only the message text.
"""


def _system(rules: str, style_guide: str) -> list[dict[str, Any]]:
    return [{
        "type": "text",
        "text": rules + "\nCandidate style guide:\n" + style_guide.strip(),
        "cache_control": {"type": "ephemeral"},
    }]


def build_request(system_rules: str, style_guide: str, user_text: str) -> dict[str, Any]:
    """Messages API request in the same shape as the cover-letter request; pure."""

    return {
        "model": COVER_LETTER_MODEL,
        "max_tokens": 4_000,
        "system": _system(system_rules, style_guide),
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_text}]}],
        "output_config": {"effort": "medium"},
        "betas": [_FALLBACK_BETA],
        "fallbacks": "default",
    }


def _complete(client: MessagesClient | None, request: dict[str, Any]) -> str:
    active = client or _anthropic_client()
    try:
        response = active.beta.messages.create(**request)
    except Exception as error:  # Provider errors may echo request details; report the type only.
        raise HunterWritingError(f"Claude request failed ({type(error).__name__}).") from None
    if getattr(response, "stop_reason", None) == "refusal":
        raise HunterWritingError("Claude declined to write this text.")
    text = "".join(
        block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise HunterWritingError("Claude returned an empty text.")
    return text


# --------------------------------------------------------------------------------------
# Checks


def unsupported_claims(text: str, allowed_text: str) -> list[str]:
    """Technologies and numbers in ``text`` that appear in none of the inputs."""

    problems: list[str] = []
    allowed_terms = set(extract_job_technologies("", allowed_text)[0])
    for term in sorted(set(extract_job_technologies("", text)[0]) - allowed_terms):
        problems.append(f"mentions {term}, which is not in the CV or company facts")
    allowed_numbers = set(_NUMBER.findall(allowed_text))
    for number in sorted(set(_NUMBER.findall(text)) - allowed_numbers):
        problems.append(f"contains the number {number}, which is not in the inputs")
    return problems


def check_text(text: str, *, allowed_text: str, max_chars: int | None = None, single_line: bool = False) -> list[str]:
    problems: list[str] = []
    if _PLACEHOLDER.search(text):
        problems.append("contains a placeholder or bracketed token")
    if single_line and ("\n" in text or "\r" in text):
        problems.append("must be a single line")
    if max_chars is not None and len(text) > max_chars:
        problems.append(f"is {len(text)} characters; the limit is {max_chars}")
    problems.extend(unsupported_claims(text, allowed_text))
    return problems


def enforce_note_limit(note: str) -> str:
    """Final guard used by every code path that stores or shows a connection note."""

    cleaned = " ".join(note.split())
    if not cleaned:
        raise HunterWritingError("The connection note is empty.")
    if len(cleaned) > LINKEDIN_NOTE_LIMIT:
        raise HunterWritingError(
            f"The connection note is {len(cleaned)} characters; LinkedIn allows {LINKEDIN_NOTE_LIMIT}."
        )
    return cleaned


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
        value = value.rsplit("```", 1)[0]
    return value.strip()


# --------------------------------------------------------------------------------------
# Generators


def generate_company_drafts(
    client: MessagesClient | None,
    company: CompanyFacts,
    person: PersonFacts | None,
    *,
    base_cv: str,
    style_guide: str,
    language: str,
) -> CompanyDrafts:
    rules = _COMMON_RULES + _DRAFT_RULES.format(
        early_words=EMAIL_WORD_LIMITS[CompanyStage.EARLY_STAGE],
        mid_words=EMAIL_WORD_LIMITS[CompanyStage.MID_SIZE],
        dm_limit=LINKEDIN_DM_LIMIT,
        language=_LANGUAGE_NAMES[language],
    )
    user = (
        "<base_cv>\n" + base_cv + "\n</base_cv>\n\n<company_facts>\n" + company.as_text() + "\n</company_facts>\n\n"
        + _person_block(person) + "Write the two variants."
    )
    allowed = base_cv + "\n" + company.as_text() + "\n" + (_person_block(person) if person else "")
    problems: list[str] = []
    for _attempt in range(_MAX_ATTEMPTS):
        request_text = user if not problems else user + "\n\nYour previous attempt was rejected: " + "; ".join(problems) + ". Fix every point."
        raw = _complete(client, build_request(rules, style_guide, request_text))
        try:
            data = json.loads(_strip_fence(raw))
        except ValueError:
            problems = ["the output was not a JSON object"]
            continue
        if not isinstance(data, dict) or not all(
            isinstance(data.get(key), str) and data[key].strip()
            for key in ("overlap", "email_subject", "email_body", "linkedin_dm")
        ):
            problems = ["the JSON must have the string keys overlap, email_subject, email_body, linkedin_dm"]
            continue
        drafts = CompanyDrafts(
            language=language,
            stage=company.stage,
            overlap=" ".join(data["overlap"].split()),
            email_subject=" ".join(data["email_subject"].split()),
            email_body=data["email_body"].strip(),
            linkedin_dm=" ".join(data["linkedin_dm"].split()),
        )
        problems = [
            f"email {item}"
            for item in check_text(
                drafts.email_subject + "\n" + drafts.email_body, allowed_text=allowed
            )
        ]
        words = len(drafts.email_body.split())
        if words > EMAIL_WORD_LIMITS[company.stage]:
            problems.append(f"email has {words} words; the limit is {EMAIL_WORD_LIMITS[company.stage]}")
        problems += [
            f"LinkedIn DM {item}"
            for item in check_text(drafts.linkedin_dm, allowed_text=allowed, max_chars=LINKEDIN_DM_LIMIT, single_line=True)
        ]
        if not problems:
            return drafts
    raise HunterWritingError("Claude's drafts failed the checks: " + "; ".join(problems[:4]))


def generate_connection_note(
    client: MessagesClient | None,
    company: CompanyFacts,
    person: PersonFacts,
    *,
    base_cv: str,
    style_guide: str,
    language: str,
    post: str | None = None,
) -> str:
    """A connection note of at most LINKEDIN_NOTE_LIMIT characters, optionally grounded in a pasted post."""

    if post is not None:
        post = post.strip()[:MAX_POST_CHARS]
        if not post:
            raise HunterWritingError("The pasted post is empty.")
    rules_template = _POST_NOTE_RULES if post else _NOTE_RULES
    rules = _COMMON_RULES + rules_template.format(limit=LINKEDIN_NOTE_LIMIT, language=_LANGUAGE_NAMES[language])
    user = (
        "<base_cv>\n" + base_cv + "\n</base_cv>\n\n<company_facts>\n" + company.as_text() + "\n</company_facts>\n\n"
        + _person_block(person)
        + (("<linkedin_post_pasted_by_candidate>\n" + post + "\n</linkedin_post_pasted_by_candidate>\n\n") if post else "")
        + "Write the connection note."
    )
    allowed = base_cv + "\n" + company.as_text() + "\n" + _person_block(person) + (post or "")
    return _short_text(client, rules, style_guide, user, allowed, LINKEDIN_NOTE_LIMIT, "connection note")


def generate_follow_up(
    client: MessagesClient | None,
    company: CompanyFacts,
    person: PersonFacts,
    *,
    base_cv: str,
    style_guide: str,
    language: str,
    previous_note: str | None = None,
) -> str:
    rules = _COMMON_RULES + _FOLLOW_UP_RULES.format(limit=LINKEDIN_DM_LIMIT, language=_LANGUAGE_NAMES[language])
    user = (
        "<base_cv>\n" + base_cv + "\n</base_cv>\n\n<company_facts>\n" + company.as_text() + "\n</company_facts>\n\n"
        + _person_block(person)
        + (("<note_the_candidate_sent>\n" + previous_note + "\n</note_the_candidate_sent>\n\n") if previous_note else "")
        + "Write the first message."
    )
    allowed = base_cv + "\n" + company.as_text() + "\n" + _person_block(person) + (previous_note or "")
    return _short_text(client, rules, style_guide, user, allowed, LINKEDIN_DM_LIMIT, "follow-up message")


def _short_text(
    client: MessagesClient | None,
    rules: str,
    style_guide: str,
    user: str,
    allowed: str,
    limit: int,
    label: str,
) -> str:
    problems: list[str] = []
    for _attempt in range(_MAX_ATTEMPTS):
        request_text = user if not problems else user + "\n\nYour previous attempt was rejected: " + "; ".join(problems) + ". Fix every point."
        text = " ".join(_complete(client, build_request(rules, style_guide, request_text)).split())
        problems = check_text(text, allowed_text=allowed, max_chars=limit, single_line=True)
        if not problems:
            return text
    raise HunterWritingError(f"Claude's {label} failed the checks: " + "; ".join(problems[:3]))


def _person_block(person: PersonFacts | None) -> str:
    if person is None:
        return ""
    lines = [f"name: {person.name}"]
    if person.role:
        lines.append(f"role: {person.role}")
    if person.quote:
        lines.append(f"public evidence: {person.quote}")
    if person.topic:
        lines.append(f"public article/talk of theirs: {person.topic}")
    return "<person_facts>\n" + "\n".join(lines) + "\n</person_facts>\n\n"
