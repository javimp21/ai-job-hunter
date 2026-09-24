"""Validated, provider-independent job data ready for ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RemotePolicy(StrEnum):
    """Where the work itself is performed."""

    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"


class RemoteEligibility(StrEnum):
    """Geographic restrictions attached to remote work."""

    SPAIN_ONLY = "SPAIN_ONLY"
    EU_REMOTE = "EU_REMOTE"
    EMEA_REMOTE = "EMEA_REMOTE"
    WORLDWIDE = "WORLDWIDE"
    COUNTRY_RESTRICTED = "COUNTRY_RESTRICTED"
    UNKNOWN = "UNKNOWN"


class SalaryPeriod(StrEnum):
    """Period represented by a salary amount."""

    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


class EmploymentType(StrEnum):
    """Normalized employment arrangement."""

    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    TEMPORARY = "TEMPORARY"
    INTERNSHIP = "INTERNSHIP"
    OTHER = "OTHER"


class NormalizedJob(BaseModel):
    """Common offer representation returned by every connector."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    external_id: str | None = Field(default=None, max_length=512)
    source_url: str | None = Field(default=None, max_length=2048)
    canonical_url: str | None = Field(default=None, max_length=2048)
    apply_url: str | None = Field(default=None, max_length=2048)
    title: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    company_website: str | None = Field(default=None, max_length=2048)
    description: str | None = None
    location: str | None = Field(default=None, max_length=255)
    remote_policy: RemotePolicy | None = None
    remote_eligibility: RemoteEligibility = RemoteEligibility.UNKNOWN
    salary_min: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    salary_max: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    salary_period: SalaryPeriod | None = None
    employment_type: EmploymentType | None = None
    published_at: datetime | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_metadata: dict[str, Any] | None = None

    @field_validator(
        "external_id",
        "source_url",
        "canonical_url",
        "apply_url",
        "company_name",
        "company_website",
        mode="before",
    )
    @classmethod
    def blank_optional_text_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def uppercase_currency_code(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("published_at", "discovered_at")
    @classmethod
    def require_timezone_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def salary_range_is_ordered(self) -> NormalizedJob:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        return self
