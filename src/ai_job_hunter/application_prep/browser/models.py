"""Private local records for inspected application forms."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ATSProvider(StrEnum):
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    ASHBY = "ASHBY"
    UNKNOWN = "UNKNOWN"


class ApplicationSessionStatus(StrEnum):
    CREATED = "CREATED"
    INSPECTED = "INSPECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    NEEDS_INPUT = "NEEDS_INPUT"
    READY_FOR_FINAL_REVIEW = "READY_FOR_FINAL_REVIEW"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ManualInterventionReason(StrEnum):
    AUTHENTICATION = "AUTHENTICATION"
    CAPTCHA = "CAPTCHA"
    UNSUPPORTED_REDIRECT = "UNSUPPORTED_REDIRECT"
    UNKNOWN_ATS = "UNKNOWN_ATS"
    NO_VISIBLE_FORM = "NO_VISIBLE_FORM"
    NETWORK_POLICY = "NETWORK_POLICY"


class FormFieldType(StrEnum):
    TEXT = "TEXT"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    URL = "URL"
    NUMBER = "NUMBER"
    DATE = "DATE"
    SELECT = "SELECT"
    MULTISELECT = "MULTISELECT"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"
    TEXTAREA = "TEXTAREA"
    FILE = "FILE"
    OTHER = "OTHER"


class CanonicalField(StrEnum):
    FIRST_NAME = "FIRST_NAME"
    LAST_NAME = "LAST_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CITY = "CITY"
    COUNTRY = "COUNTRY"
    LOCATION = "LOCATION"
    LINKEDIN = "LINKEDIN"
    GITHUB = "GITHUB"
    PORTFOLIO = "PORTFOLIO"
    CURRENT_ROLE = "CURRENT_ROLE"
    OVERALL_EXPERIENCE_YEARS = "OVERALL_EXPERIENCE_YEARS"
    SALARY_EXPECTATION = "SALARY_EXPECTATION"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    SPONSORSHIP = "SPONSORSHIP"
    LEGAL_DECLARATION = "LEGAL_DECLARATION"
    OPTIONAL_SELF_IDENTIFICATION = "OPTIONAL_SELF_IDENTIFICATION"
    CV = "CV"
    COVER_LETTER = "COVER_LETTER"
    PORTFOLIO_DOCUMENT = "PORTFOLIO_DOCUMENT"
    OTHER_DOCUMENT = "OTHER_DOCUMENT"
    CUSTOM_QUESTION = "CUSTOM_QUESTION"
    UNKNOWN = "UNKNOWN"


class MappingConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AnswerPolicy(StrEnum):
    SAFE_AUTO_FILL = "SAFE_AUTO_FILL"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    SENSITIVE = "SENSITIVE"
    LEGAL = "LEGAL"
    OPTIONAL_SELF_IDENTIFICATION = "OPTIONAL_SELF_IDENTIFICATION"
    SALARY_SUGGESTION_REVIEW = "SALARY_SUGGESTION_REVIEW"
    DOCUMENT_RECOMMENDATION_ONLY = "DOCUMENT_RECOMMENDATION_ONLY"
    TEXT_DRAFT_REVIEW = "TEXT_DRAFT_REVIEW"
    UNSUPPORTED = "UNSUPPORTED"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FormField(_FrozenModel):
    id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=1000)
    label_source: str = Field(default="label", max_length=40)
    field_type: FormFieldType
    required: bool = False
    options: tuple[str, ...] = ()
    current_value_present: bool = False
    # Minimal selectors only; values and full DOM/HTML are deliberately absent.
    dom_hint: dict[str, str | int] = Field(default_factory=dict)


class FormAction(_FrozenModel):
    label: str = Field(min_length=1, max_length=300)
    control_type: str = Field(default="button", max_length=40)
    submission_intent: bool = False
    continue_intent: bool = False
    ordinal: int = Field(default=0, ge=0)
    # Index in the button/role-button collection, used only for a gated Next.
    click_ordinal: int | None = Field(default=None, ge=0)


class ApplicationFormSnapshot(_FrozenModel):
    url: str = Field(min_length=1, max_length=2048)
    ats: ATSProvider
    step: int | None = Field(default=None, ge=1)
    step_count: int | None = Field(default=None, ge=1)
    fields: tuple[FormField, ...] = ()
    actions: tuple[FormAction, ...] = ()
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manual_intervention_required: bool = False
    manual_intervention_reason: ManualInterventionReason | None = None

    @field_validator("url")
    @classmethod
    def store_url_without_query_or_fragment(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise ValueError("application URL must be absolute HTTPS")
        host = parsed.hostname.casefold()
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit(("https", host, parsed.path, "", ""))

    @field_validator("extracted_at")
    @classmethod
    def require_aware_extracted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("extracted_at must include a timezone")
        return value


class FieldMapping(_FrozenModel):
    field_id: str = Field(min_length=1, max_length=255)
    canonical_field: CanonicalField
    confidence: MappingConfidence
    evidence: tuple[str, ...] = ()
    source_label: str = Field(min_length=1, max_length=1000)
    answer_policy: AnswerPolicy
    source_key: str | None = Field(default=None, max_length=80)
    suggested_answer: str | None = Field(default=None, max_length=5000)
    recommendation: str | None = Field(default=None, max_length=500)


class ApplicationSession(_FrozenModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    application_package_id: UUID
    url: str = Field(min_length=1, max_length=2048)
    ats: ATSProvider
    current_step: int | None = Field(default=None, ge=1)
    snapshot: ApplicationFormSnapshot | None = None
    snapshots: tuple[ApplicationFormSnapshot, ...] = ()
    mappings: tuple[FieldMapping, ...] = ()
    filled_safe_field_ids: tuple[str, ...] = ()
    pending_field_ids: tuple[str, ...] = ()
    reviewed_answer_ids: tuple[str, ...] = ()
    status: ApplicationSessionStatus = ApplicationSessionStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("url")
    @classmethod
    def store_session_url_without_query_or_fragment(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise ValueError("application URL must be absolute HTTPS")
        host = parsed.hostname.casefold()
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit(("https", host, parsed.path, "", ""))
