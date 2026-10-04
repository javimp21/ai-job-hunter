"""Typed candidate facts and preferences loaded from private JSON config."""

from __future__ import annotations

import json
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


class CandidateConfig(BaseModel):
    """A complete, validated local candidate profile and its preferences."""

    model_config = ConfigDict(extra="forbid")

    profile: CandidateProfile
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)


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
