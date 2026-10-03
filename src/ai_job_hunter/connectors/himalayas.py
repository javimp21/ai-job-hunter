"""Himalayas remote-jobs portal (public, keyless JSON search API).

Himalayas publishes, per job, the exact list of countries a remote hire may
live in (`locationRestrictions`, empty = worldwide) and often a salary range,
which makes it the best portal for "remote from Spain" roles. Its terms ask
for a visible credit/link to himalayas.app and say the data refreshes once a
day, so callers should not poll it more than daily.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)

SEARCH_URL = "https://himalayas.app/jobs/api/search"
DEFAULT_QUERIES = (
    "backend engineer",
    "backend developer",
    "software engineer",
    "platform engineer",
    "java developer",
)
_PAGE_SIZE = 20  # API maximum
_LOCATION_LIMIT = 255
_PERIODS = {
    "annual": SalaryPeriod.YEAR,
    "yearly": SalaryPeriod.YEAR,
    "monthly": SalaryPeriod.MONTH,
    "weekly": SalaryPeriod.WEEK,
    "daily": SalaryPeriod.DAY,
    "hourly": SalaryPeriod.HOUR,
}
_EMPLOYMENT_TYPES = {
    "full time": EmploymentType.FULL_TIME,
    "part time": EmploymentType.PART_TIME,
    "contractor": EmploymentType.CONTRACT,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "intern": EmploymentType.INTERNSHIP,
    "internship": EmploymentType.INTERNSHIP,
}


class HimalayasConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only)."""


class HimalayasConnector:
    provider = "himalayas"

    def __init__(
        self,
        *,
        country: str = "Spain",
        queries: Sequence[str] = DEFAULT_QUERIES,
        max_pages_per_query: int = 5,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        if max_pages_per_query < 1:
            raise ValueError("max_pages_per_query must be positive")
        if not queries:
            raise ValueError("at least one query is required")
        self.country = country
        self.queries = tuple(queries)
        self.max_pages_per_query = max_pages_per_query
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": "AI-Job-Hunter/0.1 (personal job discovery)"},
        )
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        try:
            for query in self.queries:
                cursor: str | None = None
                for _page in range(self.max_pages_per_query):
                    params: dict[str, Any] = {"q": query, "country": self.country, "limit": _PAGE_SIZE}
                    if cursor:
                        params["cursor"] = cursor
                    payload = self._get(client, params)
                    for raw in payload.get("jobs") or []:
                        if not isinstance(raw, Mapping):
                            continue
                        try:
                            job = _normalize_job(raw, discovered_at=discovered_at)
                        except ValueError:
                            continue
                        jobs.setdefault(job.external_id or job.source_url or job.title, job)
                    cursor = payload.get("nextCursor") if isinstance(payload.get("nextCursor"), str) else None
                    if not cursor:
                        break
        finally:
            if self._client is None:
                client.close()
        return list(jobs.values())

    def _get(self, client: httpx.Client, params: dict[str, Any]) -> Mapping[str, Any]:
        try:
            response = client.get(SEARCH_URL, params=params, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise HimalayasConnectorError(f"Himalayas request failed ({type(error).__name__}).") from None
        if response.status_code != 200:
            raise HimalayasConnectorError(f"Himalayas returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError:
            raise HimalayasConnectorError("Himalayas returned invalid JSON.") from None
        if not isinstance(payload, Mapping):
            raise HimalayasConnectorError("Himalayas returned an unexpected payload.")
        return payload


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("title"))
    if title is None:
        raise ValueError("title is required")
    guid = _text(raw.get("guid"))
    countries = [item for item in (raw.get("locationRestrictions") or []) if isinstance(item, str) and item.strip()]
    location, eligibility = _location(countries)
    salary_min = _decimal(raw.get("minSalary"))
    salary_max = _decimal(raw.get("maxSalary"))
    has_salary = salary_min is not None or salary_max is not None
    return NormalizedJob(
        provider=HimalayasConnector.provider,
        external_id=urlsplit(guid).path.strip("/") if guid else None,
        source_url=guid,
        canonical_url=guid,
        apply_url=_text(raw.get("applicationLink")) or guid,
        title=title,
        company_name=_text(raw.get("companyName")),
        description=html_to_text(_text(raw.get("description"))),
        location=location,
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=eligibility,
        salary_min=salary_min,
        salary_max=salary_max,
        currency=(_text(raw.get("currency")) or "").upper() or None if has_salary else None,
        salary_period=_PERIODS.get((_text(raw.get("salaryPeriod")) or "").casefold()) if has_salary else None,
        employment_type=_EMPLOYMENT_TYPES.get((_text(raw.get("employmentType")) or "").casefold()),
        published_at=_timestamp(raw.get("pubDate")),
        discovered_at=discovered_at,
        raw_metadata={key: value for key, value in raw.items() if key != "description"},
    )


def _location(countries: list[str]) -> tuple[str, RemoteEligibility]:
    if not countries:
        return "Remote — Worldwide", RemoteEligibility.WORLDWIDE
    if countries == ["Spain"]:
        return "Remote — Spain", RemoteEligibility.SPAIN_ONLY
    # Long lists (e.g. all of EMEA) don't fit the location column; keep Spain
    # visible when it is eligible so the geography check stays explicit.
    text = "Remote — " + ", ".join(countries)
    if len(text) > _LOCATION_LIMIT:
        shown = ["Spain"] if "Spain" in countries else countries[:5]
        text = f"Remote — {', '.join(shown)} (+{len(countries) - len(shown)} more countries)"
    return text, RemoteEligibility.COUNTRY_RESTRICTED


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number > 0 else None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
