"""Typed candidate facts and preferences loaded from private JSON config."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ai_job_hunter.domain.normalized_job import EmploymentType, SalaryPeriod


class SeniorityLevel(StrEnum):
    """Coarse seniority labels shared by the profile and job evaluator."""

    INTERN = "INTERN"
    GRADUATE = "GRADUATE"
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    STAFF = "STAFF"
    PRINCIPAL = "PRINCIPAL"
    LEAD = "LEAD"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    HEAD = "HEAD"
    UNKNOWN = "UNKNOWN"


class RemotePreference(StrEnum):
    """Work modes a candidate is willing to consider."""

    ANY = "ANY"
    REMOTE_ONLY = "REMOTE_ONLY"
    HYBRID_OR_REMOTE = "HYBRID_OR_REMOTE"
    ONSITE_OR_HYBRID = "ONSITE_OR_HYBRID"
    ONSITE_ONLY = "ONSITE_ONLY"


class CandidateProfile(BaseModel):
    """Candidate facts. Preferences about a future role live separately."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    years_of_experience: Decimal | None = Field(default=None, ge=0, max_digits=5, decimal_places=2)
    current_role: str | None = Field(default=None, min_length=1, max_length=255)
    current_salary: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    primary_skills: list[str] = Field(default_factory=list)
    secondary_skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    education: str | None = Field(default=None, min_length=1, max_length=500)
    current_country: str | None = Field(default=None, min_length=1, max_length=100)
    current_city: str | None = Field(default=None, min_length=1, max_length=100)
    work_authorization: list[str] = Field(default_factory=list)
    eligible_countries: list[str] = Field(default_factory=list)
    remote_work_capability: bool | None = None

    @field_validator("salary_currency", mode="before")
    @classmethod
    def normalize_profile_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "primary_skills",
        "secondary_skills",
        "technologies",
        "languages",
        "work_authorization",
        "eligible_countries",
    )
    @classmethod
    def validate_non_empty_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list items must not be empty")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def current_salary_has_currency(self) -> CandidateProfile:
        if self.current_salary is not None and self.salary_currency is None:
            raise ValueError("salary_currency is required when current_salary is set")
        return self


class CandidatePreferences(BaseModel):
    """Search constraints and preferences, kept apart from candidate facts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    preferred_roles: list[str] = Field(default_factory=list)
    minimum_salary: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    target_salary: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    salary_period: SalaryPeriod | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    acceptable_locations: list[str] = Field(default_factory=list)
    # Acceptable places the candidate would gladly move to (a smaller
    # relocation penalty than other acceptable locations).
    relocation_preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: RemotePreference = RemotePreference.ANY
    relocation_willingness: bool = False
    # False hides offers that publish no salary at all (a published salary in another currency is still judged as before).
    accept_offers_without_salary: bool = True
    # What the person's opinions taught the system (services/preference_learning.py); each change can be undone.
    excluded_title_terms: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    excluded_languages: list[str] = Field(default_factory=list)
    # Quiet hours (local hour, 0-23): no alerts from the start hour until the end hour; and a pause until a date.
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    paused_until: date | None = None
    # Sector template that classifies job titles (``src/ai_job_hunter/sectors/templates/<sector>.json``).
    sector: str = Field(default="software", pattern=r"^[a-z][a-z0-9_-]{0,40}$")
    acceptable_employment_types: list[EmploymentType] = Field(default_factory=list)
    preferred_technologies: list[str] = Field(default_factory=list)
    willing_to_learn_technologies: list[str] = Field(default_factory=list)
    minimum_seniority: SeniorityLevel | None = None
    maximum_seniority: SeniorityLevel | None = None
    international_remote_openness: bool = True
    experience_floor_shortfall_tolerance: Decimal = Field(
        default=Decimal("2"), ge=0, max_digits=5, decimal_places=2
    )
    experience_range_shortfall_tolerance: Decimal = Field(
        default=Decimal("1"), ge=0, max_digits=5, decimal_places=2
    )

    @field_validator("salary_currency", mode="before")
    @classmethod
    def normalize_preference_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "preferred_roles",
        "preferred_locations",
        "acceptable_locations",
        "relocation_preferred_locations",
        "preferred_technologies",
        "willing_to_learn_technologies",
        "excluded_title_terms",
        "excluded_companies",
        "excluded_languages",
    )
    @classmethod
    def validate_non_empty_items(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list items must not be empty")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def validate_salary_and_seniority_ranges(self) -> CandidatePreferences:
        has_salary_threshold = self.minimum_salary is not None or self.target_salary is not None
        if has_salary_threshold and (self.salary_currency is None or self.salary_period is None):
            raise ValueError(
                "salary_currency and salary_period are required when a salary threshold is set"
            )
        if (
            self.minimum_salary is not None
            and self.target_salary is not None
            and self.minimum_salary > self.target_salary
        ):
            raise ValueError("minimum_salary must not exceed target_salary")
        for name, value in (
            ("minimum_seniority", self.minimum_seniority),
            ("maximum_seniority", self.maximum_seniority),
        ):
            if value is SeniorityLevel.UNKNOWN:
                raise ValueError(f"{name} cannot be UNKNOWN")
        if (
            self.minimum_seniority is not None
            and self.maximum_seniority is not None
            and SENIORITY_ORDER[self.minimum_seniority] > SENIORITY_ORDER[self.maximum_seniority]
        ):
            raise ValueError("minimum_seniority must not exceed maximum_seniority")
        return self


class SalaryGuideEntry(BaseModel):
    """What to answer when a form asks for salary expectations in one country."""

    model_config = ConfigDict(extra="forbid")

    low: int = Field(ge=0)
    answer: int = Field(ge=0)
    high: int = Field(ge=0)
    currency: str = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def ordered(self) -> SalaryGuideEntry:
        if not self.low <= self.answer <= self.high:
            raise ValueError("salary guide needs low <= answer <= high")
        return self


class CandidateTuning(BaseModel):
    """Personal weights that only reorder results (never change eligibility).

    They are read when a feed is shown, so changing them never forces a re-evaluation, and they are
    left out of the evaluation fingerprint. Every field has a neutral default.
    """

    model_config = ConfigDict(extra="forbid")

    # Priority points lost by an on-site/hybrid role that needs a move: to an acceptable place and to
    # a destination listed in ``relocation_preferred_locations``.
    relocation_penalty: int = Field(default=15, ge=0, le=100)
    preferred_relocation_penalty: int = Field(default=5, ge=0, le=100)
    # Priority points lost by a posting that requires, or is written in, a language the candidate lacks.
    language_required_penalty: int = Field(default=25, ge=0, le=100)
    language_written_penalty: int = Field(default=15, ge=0, le=100)
    # Country name (as the prefilter spells it: "Spain", "Netherlands"...) -> suggested salary answer.
    salary_guide: dict[str, SalaryGuideEntry] = Field(default_factory=dict)
    # The person's own alert bar (priority 0-100); unset: the sector's, then the global setting.
    notify_review_min_priority: int | None = Field(default=None, ge=0, le=100)


class CandidateConfig(BaseModel):
    """A complete, validated local candidate profile and its preferences."""

    model_config = ConfigDict(extra="forbid")

    profile: CandidateProfile
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)
    tuning: CandidateTuning = Field(default_factory=CandidateTuning)


class CandidateConfigError(ValueError):
    """A readable error raised while loading candidate JSON configuration."""


SENIORITY_ORDER: dict[SeniorityLevel, int] = {
    SeniorityLevel.INTERN: 0,
    SeniorityLevel.GRADUATE: 1,
    SeniorityLevel.JUNIOR: 2,
    SeniorityLevel.MID: 3,
    SeniorityLevel.SENIOR: 4,
    SeniorityLevel.STAFF: 5,
    SeniorityLevel.PRINCIPAL: 6,
    SeniorityLevel.LEAD: 7,
    SeniorityLevel.MANAGER: 8,
    SeniorityLevel.DIRECTOR: 9,
    SeniorityLevel.HEAD: 10,
}


def load_candidate_config(path: str | Path) -> CandidateConfig:
    """Load one UTF-8 JSON config and report file/field errors without a traceback."""

    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CandidateConfigError(f"Cannot read candidate config '{config_path}': {error}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CandidateConfigError(
            f"Candidate config '{config_path}' is not valid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    try:
        return CandidateConfig.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        raise CandidateConfigError(f"Invalid candidate config '{config_path}': {details}") from error
