"""Jobicy remote-jobs API (https://jobicy.com/api/v2/remote-jobs).

Jobicy asks for attribution and a link back; its listing `url` is the page
that leads to the original application, so it is used as both source and
apply URL. `jobGeo` is free text ("Anywhere", "Spain", "Europe", ...): only
"anywhere/worldwide" and exactly "Spain" are mapped to an eligibility, other
values stay in `location` for the geography check rather than being guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import get_json, new_client
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)

API_URL = "https://jobicy.com/api/v2/remote-jobs"
_WORLDWIDE = {"anywhere", "worldwide", "global"}
_EMPLOYMENT_TYPES = {
    "full-time": EmploymentType.FULL_TIME,
    "full time": EmploymentType.FULL_TIME,
    "part-time": EmploymentType.PART_TIME,
    "part time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "freelance": EmploymentType.CONTRACT,
    "internship": EmploymentType.INTERNSHIP,
}


class JobicyConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only)."""


class JobicyConnector:
    provider = "jobicy"

    def __init__(
        self, *, geo: str = "spain", count: int = 50, client: httpx.Client | None = None, timeout: float = 20.0
    ) -> None:
        if not 1 <= count <= 100:
            raise ValueError("count must be between 1 and 100")
        self.geo = geo
        self.count = count
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or new_client(self._timeout)
        try:
            payload = get_json(
                client,
                API_URL,
                {"count": self.count, "geo": self.geo},
                portal="Jobicy",
                error=JobicyConnectorError,
                timeout=self._timeout,
            )
        finally:
            if self._client is None:
                client.close()
        if not isinstance(payload, Mapping) or not isinstance(payload.get("jobs"), list):
            raise JobicyConnectorError("Jobicy returned an unexpected payload.")
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        for raw in payload["jobs"]:
            if not isinstance(raw, Mapping):
                continue
            try:
                job = _normalize_job(raw, discovered_at=discovered_at)
            except ValueError:
                continue
            jobs.setdefault(job.external_id or job.source_url or job.title, job)
        return list(jobs.values())


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("jobTitle"))
    url = _text(raw.get("url"))
    if title is None or url is None:
        raise ValueError("jobTitle and url are required")
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in {"jobicy.com", "www.jobicy.com"}:
        raise ValueError("url must be a Jobicy listing")
    raw_id = raw.get("id")
    geos = _strings(raw.get("jobGeo"))
    folded = [geo.casefold() for geo in geos]
    if any(geo in _WORLDWIDE for geo in folded):
        location, eligibility = "Remote — Worldwide", RemoteEligibility.WORLDWIDE
    elif folded == ["spain"]:
        location, eligibility = "Remote — Spain", RemoteEligibility.SPAIN_ONLY
    elif geos:
        location, eligibility = "Remote — " + ", ".join(geos), RemoteEligibility.UNKNOWN
    else:
        location, eligibility = None, RemoteEligibility.UNKNOWN
    salary_min = _decimal(raw.get("annualSalaryMin"))
    salary_max = _decimal(raw.get("annualSalaryMax"))
    currency = (_text(raw.get("salaryCurrency")) or "").upper()
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        salary_min = salary_max = None
    has_salary = (salary_min is not None or salary_max is not None) and len(currency) == 3
    employment = next(
        (_EMPLOYMENT_TYPES[value.casefold()] for value in _strings(raw.get("jobType")) if value.casefold() in _EMPLOYMENT_TYPES),
        None,
    )
    return NormalizedJob(
        provider=JobicyConnector.provider,
        external_id=str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title,
        company_name=_text(raw.get("companyName")),
        description=html_to_text(_text(raw.get("jobDescription")) or _text(raw.get("jobExcerpt"))),
        location=location[:255] if location else None,
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=eligibility,
        salary_min=salary_min if has_salary else None,
        salary_max=salary_max if has_salary else None,
        currency=currency if has_salary else None,
        salary_period=SalaryPeriod.YEAR if has_salary else None,
        employment_type=employment,
        published_at=_timestamp(raw.get("pubDate")),
        discovered_at=discovered_at,
        raw_metadata={key: value for key, value in raw.items() if key != "jobDescription"},
    )


def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number > 0 else None


def _timestamp(value: Any) -> datetime | None:
    """Jobicy's `pubDate` has no zone in the examples seen; a naive time is not guessed."""

    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
