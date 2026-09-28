"""Typed, factual, local-only application preparation records."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _MutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class ApplicationPackageStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"  # Reserved for future manual tracking; no submit operation exists.
    CANCELLED = "CANCELLED"


class ApplicationQuestionType(StrEnum):
    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    YES_NO = "YES_NO"
    NUMBER = "NUMBER"
    SELECT = "SELECT"
    MULTISELECT = "MULTISELECT"
    URL = "URL"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    DATE = "DATE"
    FILE = "FILE"
    UNKNOWN = "UNKNOWN"


class ApplicationQuestionHandling(StrEnum):
    AUTO_ANSWERABLE = "AUTO_ANSWERABLE"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    SENSITIVE = "SENSITIVE"
    LEGAL = "LEGAL"
    UNSUPPORTED = "UNSUPPORTED"


class ApplicationAnswerStatus(StrEnum):
    UNANSWERED = "UNANSWERED"
    DRAFTED = "DRAFTED"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    USER_PROVIDED = "USER_PROVIDED"
    UNSUPPORTED = "UNSUPPORTED"


class RequirementCategory(StrEnum):
    MUST_HAVE = "MUST_HAVE"
    PREFERRED = "PREFERRED"
    RESPONSIBILITY = "RESPONSIBILITY"
    BENEFIT = "BENEFIT"
    UNKNOWN = "UNKNOWN"


class CandidateFitStatus(StrEnum):
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    LEARNABLE_GAP = "LEARNABLE_GAP"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class CandidateDocumentType(StrEnum):
    CV = "CV"
    COVER_LETTER = "COVER_LETTER"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class ApplicationReadinessStatus(StrEnum):
    READY = "READY"
    NEEDS_INPUT = "NEEDS_INPUT"
    BLOCKED = "BLOCKED"


class ApplicationReadinessReason(StrEnum):
    MISSING_REQUIRED_ANSWER = "MISSING_REQUIRED_ANSWER"
    LEGAL_QUESTION = "LEGAL_QUESTION"
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    SALARY_INPUT_REQUIRED = "SALARY_INPUT_REQUIRED"
    WORK_AUTHORIZATION_UNKNOWN = "WORK_AUTHORIZATION_UNKNOWN"
    UNSUPPORTED_FORM_FIELD = "UNSUPPORTED_FORM_FIELD"
    OTHER = "OTHER"


class QuestionSchemaStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CHECKED = "NOT_CHECKED"


class JobApplicationRequirement(_FrozenModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    category: RequirementCategory = RequirementCategory.UNKNOWN
    extracted_from: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class CandidateFit(_FrozenModel):
    requirement_id: str = Field(min_length=1, max_length=128)
    status: CandidateFitStatus
    candidate_skills: tuple[str, ...] = ()
    candidate_experience: str | None = Field(default=None, max_length=500)
    candidate_project: str | None = Field(default=None, max_length=200)
    job_requirement: str = Field(min_length=1, max_length=2000)
    evidence: tuple[str, ...] = ()


class ApplicationAnswer(_FrozenModel):
    question_id: str = Field(min_length=1, max_length=128)
    value: str | list[str] | None = None
    status: ApplicationAnswerStatus = ApplicationAnswerStatus.UNANSWERED
    evidence: tuple[str, ...] = ()
    human_review_required: bool = True


class ApplicationQuestion(_FrozenModel):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=1000)
    required: bool = False
    options: tuple[str, ...] = ()
    source_field_name: str | None = Field(default=None, max_length=255)
    normalized_type: ApplicationQuestionType = ApplicationQuestionType.UNKNOWN
    extracted_from: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = Field(default=None, max_length=2000)
    handling: ApplicationQuestionHandling = ApplicationQuestionHandling.NEEDS_USER_INPUT
    answer: str | list[str] | None = None
    answer_status: ApplicationAnswerStatus = ApplicationAnswerStatus.UNANSWERED
    answer_evidence: tuple[str, ...] = ()
    human_review_required: bool = True


class CandidateDocument(_FrozenModel):
    type: CandidateDocumentType
    id: str = Field(min_length=1, max_length=160)
    local_path: str = Field(
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("local_path", "local_reference"),
    )
    # `name` and `local_reference` are accepted for backwards compatibility
    # with application packages created before candidate_documents.local.json.
    name: str | None = Field(default=None, min_length=1, max_length=160)
    tags: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()
    role_families: tuple[str, ...] = ()
    language: str | None = Field(default=None, max_length=80)
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_document_metadata(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        legacy_path = result.get("local_reference")
        if "local_path" not in result and isinstance(legacy_path, str):
            result["local_path"] = legacy_path
        result.pop("local_reference", None)
        if "id" not in result:
            label = result.get("name") or result.get("local_path") or legacy_path
            if isinstance(label, str) and label.strip():
                result["id"] = Path(label).stem[:160] or "candidate-document"
        return result

    @property
    def local_reference(self) -> str:
        """Legacy read-only alias; file contents are never opened by this model."""

        return self.local_path

    @property
    def display_name(self) -> str:
        return self.name or self.id

    @field_validator("updated_at")
    @classmethod
    def require_aware_updated_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("updated_at must include a timezone")
        return value


class CandidateWritingStyle(_FrozenModel):
    concise: bool = True
    direct: bool = True
    tone: str = Field(default="informal-professional", min_length=1, max_length=80)
    max_words_short_answer: int = Field(default=80, ge=20, le=300)
    avoid_buzzwords: bool = True


class ApplicationReadiness(_FrozenModel):
    status: ApplicationReadinessStatus
    reasons: tuple[ApplicationReadinessReason, ...] = ()
    details: tuple[str, ...] = ()


class ApplicationPackage(_MutableModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    application_id: UUID | None = None
    version: str = Field(default="assisted-application-v1", min_length=1, max_length=100)
    fingerprint: str = Field(min_length=16, max_length=128)
    candidate_profile_fingerprint: str = Field(min_length=16, max_length=128)
    candidate_preferences_fingerprint: str = Field(min_length=16, max_length=128)
    status: ApplicationPackageStatus = ApplicationPackageStatus.READY_FOR_REVIEW
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    job_title: str = Field(default="", max_length=512)
    company_name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    technologies: tuple[str, ...] = ()
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = Field(default=None, max_length=8)
    salary_period: str | None = Field(default=None, max_length=32)
    canonical_job_url: str | None = Field(default=None, max_length=2048)
    application_url: str | None = Field(default=None, max_length=2048)
    source_ats: str | None = Field(default=None, max_length=100)
    source_snapshot_at: datetime | None = None
    question_schema_status: QuestionSchemaStatus = QuestionSchemaStatus.NOT_CHECKED
    question_schema_evidence: str | None = Field(default=None, max_length=2000)
    requirements: list[JobApplicationRequirement] = Field(default_factory=list)
    requirements_summary: str = "No explicit application requirements extracted."
    candidate_fit: list[CandidateFit] = Field(default_factory=list)
    candidate_fit_summary: str = "Candidate fit has not been assessed."
    missing_information: list[str] = Field(default_factory=list)
    suggested_cv_variant: str | None = Field(default=None, max_length=160)
    suggested_cover_letter: str | None = None
    questions: list[ApplicationQuestion] = Field(default_factory=list)
    answers: list[ApplicationAnswer] = Field(default_factory=list)
    readiness: ApplicationReadiness = Field(
        default_factory=lambda: ApplicationReadiness(
            status=ApplicationReadinessStatus.NEEDS_INPUT,
            reasons=(ApplicationReadinessReason.OTHER,),
            details=("Readiness has not been assessed.",),
        )
    )
    notes: list[str] = Field(default_factory=list)

    @field_validator("created_at", "updated_at", "source_snapshot_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value

    @field_validator("status")
    @classmethod
    def block_automatic_submitted_status(cls, value: ApplicationPackageStatus) -> ApplicationPackageStatus:
        # SUBMITTED remains part of the conceptual vocabulary, but preparation
        # code cannot create or transition a package to it.
        if value is ApplicationPackageStatus.SUBMITTED:
            raise ValueError("SUBMITTED is reserved; this application-preparation package cannot submit")
        return value

    def sync_answers_from_questions(self) -> None:
        self.answers = [
            ApplicationAnswer(
                question_id=question.id,
                value=question.answer,
                status=question.answer_status,
                evidence=question.answer_evidence,
                human_review_required=question.human_review_required,
            )
            for question in self.questions
            if question.answer is not None or question.answer_status is not ApplicationAnswerStatus.UNANSWERED
        ]
