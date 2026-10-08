"""Letters and interview briefs for people who signed up (no private files: their stored experience summary instead).

Asking again for the same job returns the stored document without paying or counting a use; a new one is checked against
the person's quota first. Everything is stored in the database under the person, nothing on disk.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.models import Job
from ai_job_hunter.models.usage import GeneratedDocument
from ai_job_hunter.models.user import UserProfile
from ai_job_hunter.services import usage
from ai_job_hunter.services.cover_letters import (
    COVER_LETTER_MODEL,
    PERSON_STYLE_GUIDE,
    CoverLetterError,
    _anthropic_client,
    _detect_language,
    _posting_facts,
    _validate_language,
    write_letter_for_person,
)
from ai_job_hunter.services.interview_prep import build_interview_request

LETTER = usage.LETTER
INTERVIEW = usage.INTERVIEW


class QuotaExceeded(CoverLetterError):
    """The person reached a limit; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class PersonDocument:
    kind: str
    company: str
    title: str
    language: str
    text: str
    reused: bool


class PersonDocuments:
    def __init__(self, session_factory: Callable[[], Session], client=None) -> None:  # noqa: ANN001
        self._sessions = session_factory
        self._client = client

    def letter(self, user_id: UUID, job_id: UUID, language: str = "auto") -> PersonDocument:
        return self._get(user_id, job_id, LETTER, language)

    def interview(self, user_id: UUID, job_id: UUID) -> PersonDocument:
        return self._get(user_id, job_id, INTERVIEW, "auto")

    def _get(self, user_id: UUID, job_id: UUID, kind: str, language: str) -> PersonDocument:
        _validate_language(language)
        with acting_as(user_id), self._sessions() as session:
            job = session.scalar(
                select(Job).options(joinedload(Job.company), selectinload(Job.sources)).where(Job.id == job_id)
            )
            if job is None:
                raise CoverLetterError("Esa oferta ya no está disponible.")
            posting = _posting_facts(job)
            names = (posting["company"], posting["title"])
            stored = session.scalar(
                select(GeneratedDocument).where(
                    GeneratedDocument.job_id == job_id,
                    GeneratedDocument.kind == kind,
                    GeneratedDocument.language == language,
                )
            )
            if stored is not None:
                return PersonDocument(kind, *names, stored.language, stored.text, reused=True)
            decision = usage.check_quota(session, kind)
            if not decision.allowed:
                raise QuotaExceeded(decision.message or "Límite alcanzado.")
            profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
            if profile is None:
                raise CoverLetterError("Todavía no tienes perfil.")
            candidate = CandidateConfig.model_validate(profile.config)
            cv_text = profile.cv_text
            session.rollback()
            if kind == LETTER:
                text, resolved, model = write_letter_for_person(
                    session, candidate, posting, cv_text, language=language, client=self._client
                )
            else:
                text, resolved, model = _write_interview(posting, cv_text, client=self._client)
            session.add(GeneratedDocument(job_id=job_id, kind=kind, language=language, text=text, model=model))
            usage.record_usage(session, kind, job_id)
            session.commit()
            return PersonDocument(kind, *names, resolved, text, reused=False)


def _write_interview(posting: dict, cv_text: str | None, *, client) -> tuple[str, str, str]:  # noqa: ANN001
    if not cv_text:
        raise CoverLetterError("Para preparar la entrevista necesito el resumen de tu experiencia y no lo tengo guardado.")
    language = _detect_language(posting.get("description") or posting["title"])
    request = build_interview_request(posting=posting, base_cv=cv_text, style_guide=PERSON_STYLE_GUIDE, language=language)
    try:
        response = (client or _anthropic_client()).beta.messages.create(**request)
    except Exception as error:  # noqa: BLE001 - provider errors may echo request details
        raise CoverLetterError(f"Claude request failed ({type(error).__name__}).") from None
    if getattr(response, "stop_reason", None) == "refusal":
        raise CoverLetterError("Claude declined to write this brief.")
    text = "".join(
        block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise CoverLetterError("Claude returned an empty brief.")
    return text, language, getattr(response, "model", COVER_LETTER_MODEL)
