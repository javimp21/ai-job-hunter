"""Factual package construction and human-controlled local lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from ai_job_hunter.application_prep.drafting import draft_answers
from ai_job_hunter.application_prep.extraction import (
    extract_application_questions,
    extract_job_requirements,
)
from ai_job_hunter.application_prep.fit import map_candidate_fit
from ai_job_hunter.application_prep.models import (
    ApplicationAnswer,
    ApplicationAnswerStatus,
    ApplicationPackage,
    ApplicationPackageStatus,
    ApplicationQuestion,
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    ApplicationReadiness,
    ApplicationReadinessReason,
    ApplicationReadinessStatus,
    CandidateDocument,
    CandidateDocumentType,
    CandidateWritingStyle,
    JobApplicationRequirement,
    QuestionSchemaStatus,
)
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.outreach.projects import CandidateProject, select_relevant_project


class ApplicationPreparationError(ValueError):
    """Safe workflow error; never includes answer values or source payloads."""


@dataclass(frozen=True, slots=True)
class ApplicationJobInput:
    job_id: UUID
    title: str
    company: str | None
    description: str | None
    provider: str | None
    canonical_job_url: str | None
    application_url: str | None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    source_snapshot_at: datetime | None = None
    application_id: UUID | None = None
    technologies: tuple[str, ...] = ()
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    location: str | None = None


def build_application_package(
    job: ApplicationJobInput,
    candidate: CandidateConfig,
    *,
    projects: Sequence[CandidateProject] = (),
    documents: Sequence[CandidateDocument] = (),
    writing_style: CandidateWritingStyle | None = None,
    question_schema_status: QuestionSchemaStatus = QuestionSchemaStatus.NOT_CHECKED,
    question_schema_evidence: str | None = None,
    request_cover_letter: bool = False,
) -> ApplicationPackage:
    """Prepare a local draft from supplied job/profile facts; never contacts an ATS."""

    requirements = extract_job_requirements(job.description)
    questions = extract_application_questions(job.raw_metadata, provider=job.provider or "unknown")
    project_selection = select_relevant_project(job.title, job.technologies, projects)
    selected_projects = (project_selection.project,) if project_selection.project else ()
    questions = draft_answers(
        questions,
        candidate=candidate,
        job_title=job.title,
        job_description=job.description or "",
        projects=selected_projects,
        writing_style=writing_style or CandidateWritingStyle(),
    )
    fit = map_candidate_fit(requirements, candidate, projects=projects)
    cv_variant = recommend_cv_variant(job.title, job.technologies, requirements, documents)
    cover_required = request_cover_letter or _description_requires_cover_letter(job.description)
    suggested_cover_letter = (
        _draft_cover_letter(job, candidate, project_selection.project, writing_style or CandidateWritingStyle())
        if cover_required
        else None
    )

    missing: list[str] = []
    if not documents:
        missing.append("No candidate_documents.local.json is configured; a CV variant cannot be recommended.")
    elif cv_variant is None:
        missing.append("No configured CV metadata matches this job strongly enough for a recommendation.")
    if question_schema_status is not QuestionSchemaStatus.AVAILABLE:
        missing.append("The complete application form schema is unavailable; inspect the hosted form manually.")
    for question in questions:
        if question.required and question.answer_status in {
            ApplicationAnswerStatus.NEEDS_USER_INPUT,
            ApplicationAnswerStatus.UNANSWERED,
            ApplicationAnswerStatus.UNSUPPORTED,
        }:
            missing.append(f"Required question needs attention: {question.label}")
    if cover_required and not documents:
        missing.append("The posting requests a cover letter, but no local cover-letter document is configured.")

    package = ApplicationPackage(
        job_id=job.job_id,
        application_id=job.application_id,
        fingerprint=_fingerprint(
            {
                "job_id": str(job.job_id),
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "technologies": job.technologies,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
                "salary_period": job.salary_period,
                "description": job.description,
                "provider": job.provider,
                "canonical_job_url": job.canonical_job_url,
                "application_url": job.application_url,
                "candidate_profile": candidate.profile.model_dump(mode="json"),
                "candidate_preferences": candidate.preferences.model_dump(mode="json"),
                "writing_style": (writing_style or CandidateWritingStyle()).model_dump(mode="json"),
                "documents": [item.model_dump(mode="json") for item in documents],
                "projects": [item.model_dump(mode="json") for item in projects],
            }
        ),
        candidate_profile_fingerprint=_fingerprint(candidate.profile.model_dump(mode="json")),
        candidate_preferences_fingerprint=_fingerprint(candidate.preferences.model_dump(mode="json")),
        job_title=job.title,
        company_name=job.company,
        location=job.location,
        technologies=job.technologies,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        salary_period=job.salary_period,
        canonical_job_url=job.canonical_job_url,
        application_url=job.application_url,
        source_ats=job.provider,
        source_snapshot_at=job.source_snapshot_at,
        question_schema_status=question_schema_status,
        question_schema_evidence=question_schema_evidence,
        requirements=requirements,
        requirements_summary=_summarize_requirements(requirements),
        candidate_fit=fit,
        candidate_fit_summary=_summarize_fit(fit),
        missing_information=list(dict.fromkeys(missing)),
        suggested_cv_variant=cv_variant,
        suggested_cover_letter=suggested_cover_letter,
        questions=questions,
    )
    package.sync_answers_from_questions()
    package.readiness = assess_readiness(package)
    return package


def recommend_cv_variant(
    job_title: str,
    job_technologies: Sequence[str],
    requirements: Sequence[JobApplicationRequirement],
    documents: Sequence[CandidateDocument],
) -> str | None:
    """Choose a configured CV only when explicit role or technology metadata overlaps."""

    cv_documents = [item for item in documents if item.type is CandidateDocumentType.CV]
    if not cv_documents:
        return None
    job_terms = _terms(job_title)
    job_tech = {_canonical(item) for item in job_technologies}
    for requirement in requirements:
        job_tech.update(_technologies_in(requirement.text))
    ranked: list[tuple[int, int, CandidateDocument]] = []
    for index, document in enumerate(cv_documents):
        doc_terms = {_canonical(item) for item in (*document.tags, *document.role_families)}
        doc_terms.update(_terms(" ".join((*document.tags, *document.role_families))))
        doc_tech = {_canonical(item) for item in document.technologies}
        score = 3 * len(job_tech & doc_tech) + len(job_terms & doc_terms)
        if score:
            ranked.append((score, -index, document))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (-row[0], -row[1]))
    return ranked[0][2].name


def assess_readiness(package: ApplicationPackage) -> ApplicationReadiness:
    reasons: list[ApplicationReadinessReason] = []
    details: list[str] = []
    blocked = False
    needs_input = package.question_schema_status is not QuestionSchemaStatus.AVAILABLE
    if package.question_schema_status is not QuestionSchemaStatus.AVAILABLE:
        reasons.append(ApplicationReadinessReason.OTHER)
        details.append("Verify the hosted application form because a complete schema is unavailable.")

    for question in package.questions:
        if not question.required:
            continue
        if question.normalized_type is ApplicationQuestionType.FILE:
            blocked = True
            reasons.append(ApplicationReadinessReason.MISSING_DOCUMENT)
            details.append(f"Required file field has no configured local document: {question.label}")
            if question.handling is ApplicationQuestionHandling.UNSUPPORTED:
                reasons.append(ApplicationReadinessReason.UNSUPPORTED_FORM_FIELD)
                details.append(f"Required file field cannot be supplied by this local workflow: {question.label}")
            continue
        if question.handling is ApplicationQuestionHandling.UNSUPPORTED:
            blocked = True
            reasons.append(ApplicationReadinessReason.UNSUPPORTED_FORM_FIELD)
            details.append(f"Required form field is unsupported: {question.label}")
            continue
        if question.answer is None or question.answer_status in {
            ApplicationAnswerStatus.UNANSWERED,
            ApplicationAnswerStatus.NEEDS_USER_INPUT,
            ApplicationAnswerStatus.UNSUPPORTED,
            ApplicationAnswerStatus.REVIEW_REQUIRED,
        }:
            needs_input = True
            if question.handling is ApplicationQuestionHandling.LEGAL:
                reasons.append(ApplicationReadinessReason.LEGAL_QUESTION)
                if _is_work_authorization_question(question.label):
                    reasons.append(ApplicationReadinessReason.WORK_AUTHORIZATION_UNKNOWN)
                details.append(f"Answer and review legal question manually: {question.label}")
            elif _is_salary_question(question.label):
                reasons.append(ApplicationReadinessReason.SALARY_INPUT_REQUIRED)
                details.append(f"Review salary expectation manually: {question.label}")
            elif question.handling is ApplicationQuestionHandling.SENSITIVE:
                reasons.append(ApplicationReadinessReason.LEGAL_QUESTION)
                details.append(f"Sensitive question remains for the user: {question.label}")
            else:
                reasons.append(ApplicationReadinessReason.MISSING_REQUIRED_ANSWER)
                details.append(f"Required answer needs user input or review: {question.label}")

    if not package.application_url:
        needs_input = True
        reasons.append(ApplicationReadinessReason.OTHER)
        details.append("No direct hosted application URL is available; use the canonical job URL to verify entry point.")
    if blocked:
        status = ApplicationReadinessStatus.BLOCKED
    elif needs_input:
        status = ApplicationReadinessStatus.NEEDS_INPUT
    else:
        status = ApplicationReadinessStatus.READY
    return ApplicationReadiness(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        details=tuple(dict.fromkeys(details)),
    )


def answer_application_question(
    package: ApplicationPackage,
    question_id: str,
    value: str | Sequence[str],
    *,
    confirm_sensitive: bool = False,
) -> ApplicationPackage:
    """Save explicit human input locally; this function cannot submit it."""

    if package.status in {ApplicationPackageStatus.CANCELLED, ApplicationPackageStatus.SUBMITTED}:
        raise ApplicationPreparationError("This package is not editable in its current status.")
    question = next((item for item in package.questions if item.id == question_id), None)
    if question is None:
        raise ApplicationPreparationError("Application question was not found.")
    if question.handling in {ApplicationQuestionHandling.LEGAL, ApplicationQuestionHandling.SENSITIVE} and not confirm_sensitive:
        raise ApplicationPreparationError(
            "This is a legal or sensitive field. Re-run with explicit confirmation to store your own answer."
        )
    if question.normalized_type in {ApplicationQuestionType.FILE, ApplicationQuestionType.UNKNOWN}:
        raise ApplicationPreparationError("This field cannot be answered by the local preparation workflow.")
    answer = _validate_answer(question, value)
    updated_question = question.model_copy(
        update={
            "answer": answer,
            "answer_status": ApplicationAnswerStatus.USER_PROVIDED,
            "answer_evidence": ("Entered explicitly by the user.",),
            "human_review_required": True,
        }
    )
    package.questions = [updated_question if item.id == question_id else item for item in package.questions]
    package.status = ApplicationPackageStatus.READY_FOR_REVIEW
    package.updated_at = datetime.now(UTC)
    package.sync_answers_from_questions()
    package.readiness = assess_readiness(package)
    return package


def mark_ready_to_submit(package: ApplicationPackage) -> ApplicationPackage:
    """Record an explicit human review decision; does not submit or contact an ATS."""

    if package.status is ApplicationPackageStatus.CANCELLED:
        raise ApplicationPreparationError("Cancelled packages cannot be marked ready.")
    readiness = assess_readiness(package)
    package.readiness = readiness
    if readiness.status is not ApplicationReadinessStatus.READY:
        raise ApplicationPreparationError("Package still needs input or has unsupported required fields.")
    package.status = ApplicationPackageStatus.READY_TO_SUBMIT
    package.updated_at = datetime.now(UTC)
    return package


def cancel_application_package(package: ApplicationPackage) -> ApplicationPackage:
    if package.status is ApplicationPackageStatus.SUBMITTED:
        raise ApplicationPreparationError("Submitted packages cannot be cancelled here.")
    package.status = ApplicationPackageStatus.CANCELLED
    package.updated_at = datetime.now(UTC)
    return package


def _validate_answer(
    question: ApplicationQuestion,
    value: str | Sequence[str],
) -> str | list[str]:
    if question.normalized_type is ApplicationQuestionType.MULTISELECT:
        choices = list(value) if not isinstance(value, str) else [part.strip() for part in value.split(",")]
        if not choices or any(not item for item in choices):
            raise ApplicationPreparationError("Provide one or more valid options.")
        allowed = {item.casefold(): item for item in question.options}
        if not allowed or any(item.casefold() not in allowed for item in choices):
            raise ApplicationPreparationError("Answer must match the listed options.")
        return [allowed[item.casefold()] for item in choices]
    if isinstance(value, Sequence) and not isinstance(value, str):
        raise ApplicationPreparationError("This field accepts one answer value.")
    answer = value.strip()
    if not answer:
        raise ApplicationPreparationError("Answer must not be blank.")
    if question.normalized_type is ApplicationQuestionType.YES_NO:
        normalized = answer.casefold()
        if normalized in {"yes", "y", "true"}:
            return "Yes"
        if normalized in {"no", "n", "false"}:
            return "No"
        raise ApplicationPreparationError("Enter Yes or No.")
    if question.normalized_type is ApplicationQuestionType.SELECT:
        allowed = {item.casefold(): item for item in question.options}
        if answer.casefold() not in allowed:
            raise ApplicationPreparationError("Answer must match one of the listed options.")
        return allowed[answer.casefold()]
    if question.normalized_type is ApplicationQuestionType.NUMBER:
        try:
            Decimal(answer)
        except InvalidOperation as error:
            raise ApplicationPreparationError("Enter a numeric answer.") from error
    if question.normalized_type is ApplicationQuestionType.URL:
        parsed = urlsplit(answer)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ApplicationPreparationError("Enter an absolute HTTP(S) URL.")
    if question.normalized_type is ApplicationQuestionType.EMAIL and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", answer):
        raise ApplicationPreparationError("Enter a valid email address.")
    if question.normalized_type is ApplicationQuestionType.DATE and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", answer):
        raise ApplicationPreparationError("Enter a date in YYYY-MM-DD format.")
    if question.options and question.normalized_type in {ApplicationQuestionType.TEXT, ApplicationQuestionType.TEXTAREA}:
        # Free-form types may have labels for context; preserve the exact text.
        return answer
    return answer


def _summarize_requirements(requirements: Sequence[JobApplicationRequirement]) -> str:
    counts: dict[str, int] = {}
    for item in requirements:
        counts[item.category.value] = counts.get(item.category.value, 0) + 1
    if not counts:
        return "No discrete requirements could be extracted from the saved posting text."
    return ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))


def _summarize_fit(fit: Sequence[Any]) -> str:
    if not fit:
        return "No explicit requirements were available to map against the configured profile."
    counts: dict[str, int] = {}
    for item in fit:
        key = item.status.value
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))


def _draft_cover_letter(
    job: ApplicationJobInput,
    candidate: CandidateConfig,
    project: CandidateProject | None,
    style: CandidateWritingStyle,
) -> str:
    facts: list[str] = []
    profile = candidate.profile
    if profile.current_role:
        facts.append(f"I currently work as a {profile.current_role}.")
    if profile.years_of_experience is not None:
        years = format(profile.years_of_experience.normalize(), "f")
        facts.append(f"I have {years} years of experience.")
    skills = list(dict.fromkeys([*profile.primary_skills, *profile.technologies]))[:4]
    if skills:
        facts.append("My configured experience includes " + ", ".join(skills) + ".")
    if project:
        facts.append(f"A relevant project is {project.name}: {project.short_description}")
    if not facts:
        facts.append("I would like to discuss how my background fits the published role requirements.")
    focus = _posting_focus(job.description)
    if focus:
        facts.append(f"The posting highlights {focus}.")
    body = f"Hello {job.company or 'Hiring Team'},\n\nI am writing about {job.title}. " + " ".join(facts)
    body += "\n\nRegards,"
    return _limit_words(body, style.max_words_short_answer * 2) if style.concise else body


def _posting_focus(description: str | None) -> str | None:
    if not description:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", description):
        clean = " ".join(sentence.split())
        if 20 <= len(clean) <= 240 and any(term in clean.casefold() for term in ("build", "develop", "maintain", "platform", "services", "data pipeline")):
            return clean.rstrip(".")
    return None


def _description_requires_cover_letter(description: str | None) -> bool:
    if not description:
        return False
    return bool(re.search(r"(?:required|must|please include|submit)\D{0,50}cover letter|cover letter\D{0,50}(?:required|must|include)", description, re.I))


def _is_salary_question(label: str) -> bool:
    return bool(re.search(r"salary|compensation|expected pay|remuneration", label, re.I))


def _is_work_authorization_question(label: str) -> bool:
    return bool(
        re.search(
            r"work authori[sz]|authorized to work|eligible to work|legally authorized|"
            r"legally work|right to work|sponsor|visa|immigration",
            label,
            re.I,
        )
    )


def _terms(value: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9+#.]+", value.casefold()) if len(part) > 1}


def _canonical(value: str) -> str:
    return " ".join(value.casefold().replace(".", " ").replace("-", " ").split())


def _technologies_in(value: str) -> set[str]:
    known = (
        "Java", "Kotlin", "Python", "Go", "Node.js", "TypeScript", "JavaScript", "AWS", "GCP", "Azure",
        "Kubernetes", "Docker", "Kafka", "Redis", "PostgreSQL", "SQL", "Spark", "Airflow", "dbt",
        "Terraform", "Spring", "C#", ".NET", "Ruby", "Rails", "Elixir", "Rust", "Scala", "PHP", "React",
    )
    return {item for item in known if re.search(rf"(?<![\w]){re.escape(item)}(?![\w])", value, re.I)}


def _limit_words(value: str, limit: int) -> str:
    words = value.split()
    return " ".join(words[:limit])


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
