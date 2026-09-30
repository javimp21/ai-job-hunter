"""Deterministic, provider-independent facts extracted from job records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ai_job_hunter.candidates.profile import SENIORITY_ORDER, SeniorityLevel
from ai_job_hunter.candidates.technologies import extract_job_technologies
from ai_job_hunter.deduplication.normalization import normalize_job_title
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)

if TYPE_CHECKING:
    from ai_job_hunter.models.job import Job
    from ai_job_hunter.models.job_source import JobSource


_LEVEL_LABEL = re.compile(
    r"\b(?:seniority|level)\s*[:=\-]\s*"
    r"(?P<level>intern(?:ship)?|graduate|junior|jr|mid(?:dle)?|intermediate|"
    r"senior|sr|staff|principal|lead|manager|director|head)\b",
    re.IGNORECASE,
)
_SENIORITY_ALIASES = {
    "internship": SeniorityLevel.INTERN,
    "jr": SeniorityLevel.JUNIOR,
    "middle": SeniorityLevel.MID,
    "intermediate": SeniorityLevel.MID,
    "sr": SeniorityLevel.SENIOR,
}


@dataclass(frozen=True, slots=True)
class JobFacts:
    """Small extracted offer facts. No unstructured fact is inferred by AI."""

    title: str
    normalized_title: str
    inferred_seniority: SeniorityLevel
    remote_policy: RemotePolicy | None
    remote_eligibility: RemoteEligibility
    location: str | None
    technologies: tuple[str, ...]
    required_technologies: tuple[str, ...]
    salary_min: Decimal | None
    salary_max: Decimal | None
    currency: str | None
    salary_period: SalaryPeriod | None
    employment_type: EmploymentType | None

    @classmethod
    def from_normalized_job(cls, offer: NormalizedJob) -> JobFacts:
        return cls._from_values(
            title=offer.title,
            description=offer.description,
            location=offer.location,
            remote_policy=offer.remote_policy,
            remote_eligibility=offer.remote_eligibility,
            salary_min=offer.salary_min,
            salary_max=offer.salary_max,
            currency=offer.currency,
            salary_period=offer.salary_period,
            employment_type=offer.employment_type,
        )

    @classmethod
    def from_job_source(cls, job: Job, source: JobSource) -> JobFacts:
        """Build facts from a source's latest provider snapshot when available."""

        return cls._from_values(
            title=(getattr(source, "source_title", None) or job.title),
            description=(
                source.source_description
                if hasattr(source, "source_description")
                else job.description
            ),
            location=(
                source.source_location
                if hasattr(source, "source_location")
                else job.location
            ),
            remote_policy=source.remote_policy or job.remote_policy,
            remote_eligibility=source.remote_eligibility,
            salary_min=source.salary_min,
            salary_max=source.salary_max,
            currency=source.salary_currency,
            salary_period=source.salary_period,
            employment_type=source.employment_type,
        )

    @classmethod
    def _from_values(
        cls,
        *,
        title: str,
        description: str | None,
        location: str | None,
        remote_policy: Any,
        remote_eligibility: Any,
        salary_min: Decimal | None,
        salary_max: Decimal | None,
        currency: str | None,
        salary_period: Any,
        employment_type: Any,
    ) -> JobFacts:
        normalized = normalize_job_title(title)
        title_levels = {_seniority(token) for token in normalized.seniority}
        title_levels.discard(SeniorityLevel.UNKNOWN)
        if title_levels:
            # Composite labels such as "Senior/Staff" indicate at least the
            # highest stated level; choosing the higher level is conservative.
            level = max(title_levels, key=SENIORITY_ORDER.__getitem__)
        else:
            label = _LEVEL_LABEL.search(description or "")
            level = _seniority(label.group("level")) if label else SeniorityLevel.UNKNOWN
        technologies, required = extract_job_technologies(title, description)
        return cls(
            title=title,
            normalized_title=" ".join(sorted(normalized.tokens)),
            inferred_seniority=level,
            remote_policy=_enum_value(RemotePolicy, remote_policy),
            remote_eligibility=_enum_value(RemoteEligibility, remote_eligibility)
            or RemoteEligibility.UNKNOWN,
            location=location,
            technologies=technologies,
            required_technologies=required,
            salary_min=salary_min,
            salary_max=salary_max,
            currency=currency.upper() if currency else None,
            salary_period=_enum_value(SalaryPeriod, salary_period),
            employment_type=_enum_value(EmploymentType, employment_type),
        )


def _seniority(value: str) -> SeniorityLevel:
    token = value.casefold().strip()
    if token in _SENIORITY_ALIASES:
        return _SENIORITY_ALIASES[token]
    try:
        return SeniorityLevel(token.upper())
    except ValueError:
        return SeniorityLevel.UNKNOWN


def _enum_value(enum_type: type[Any], value: Any) -> Any | None:
    if value is None:
        return None
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return None
