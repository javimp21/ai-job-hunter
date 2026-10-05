"""4dayweek.io public jobs API (https://4dayweek.io/api/v2/jobs).

The site documents a free, no-auth JSON API (60 requests/minute/IP, robots.txt
allows /api/v2) and asks for a link back, so alerts credit 4dayweek.io and
`apply_url` is the listing. Only the API's own filters are used (remote work
arrangement, engineering category, posted in the last days). `locations` lists
the countries where remote work is allowed; they stay in `location` for the
geography check and are never widened. Salary units are ambiguous in the live
data (values look like minor units while the docs speak of dollars), so salary
is not mapped and stays in `raw_metadata`.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import get_json, new_client
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemoteEligibility, RemotePolicy

API_URL = "https://4dayweek.io/api/v2/jobs"
_LOCATION_LIMIT = 255
_EMPLOYMENT_TYPES = {
    "permanent": EmploymentType.FULL_TIME,
    "contract": EmploymentType.CONTRACT,
    "part_time": EmploymentType.PART_TIME,
    "internship": EmploymentType.INTERNSHIP,
}


class FourDayWeekConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only)."""


class FourDayWeekConnector:
    provider = "fourdayweek"

    def __init__(
        self,
        *,
        posted_after_days: int = 7,
        max_pages: int = 3,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        pause_seconds: float = 2.0,
    ) -> None:
        if not 1 <= posted_after_days <= 365:
            raise ValueError("posted_after_days must be between 1 and 365")
        if not 1 <= max_pages <= 10:
            raise ValueError("max_pages must be between 1 and 10")
        self.posted_after_days = posted_after_days
        self.max_pages = max_pages
        self._client = client
        self._timeout = timeout
        self._pause = pause_seconds

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or new_client(self._timeout)
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        try:
            for page in range(1, self.max_pages + 1):
                if page > 1:
                    time.sleep(self._pause)
                payload = get_json(
                    client,
                    API_URL,
                    {
                        "work_arrangement": "remote",
                        "category": "engineering",
                        "posted_after": self.posted_after_days,
                        "limit": 100,
                        "page": page,
                    },
                    portal="4dayweek.io",
                    error=FourDayWeekConnectorError,
                    timeout=self._timeout,
                )
                if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                    raise FourDayWeekConnectorError("4dayweek.io returned an unexpected payload.")
                for raw in payload["data"]:
                    if not isinstance(raw, Mapping):
                        continue
                    try:
                        job = _normalize_job(raw, discovered_at=discovered_at)
                    except ValueError:
                        continue
                    jobs.setdefault(job.external_id or job.source_url or job.title, job)
                if payload.get("has_more") is not True:
                    break
        finally:
            if self._client is None:
                client.close()
        return list(jobs.values())


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("title"))
    url = _text(raw.get("url"))
    if title is None or url is None:
        raise ValueError("title and url are required")
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in {"4dayweek.io", "www.4dayweek.io"}:
        raise ValueError("url must be a 4dayweek.io listing")
    company = raw.get("company") if isinstance(raw.get("company"), Mapping) else {}
    countries = _countries(raw.get("locations"))
    location, eligibility = _location(countries)
    return NormalizedJob(
        provider=FourDayWeekConnector.provider,
        external_id=_text(raw.get("slug")) or _text(raw.get("id")),
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title[:255],
        company_name=(_text(company.get("name")) or "")[:255] or None,
        company_website=_https_url(company.get("website")),
        description=html_to_text(_text(raw.get("description"))),
        location=location,
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=eligibility,
        employment_type=_EMPLOYMENT_TYPES.get((_text(raw.get("contract_type")) or "").casefold()),
        published_at=_timestamp(raw.get("posted_at")),
        discovered_at=discovered_at,
        raw_metadata={key: value for key, value in raw.items() if key != "description"},
    )


def _countries(locations: Any) -> list[str]:
    names: list[str] = []
    for entry in locations if isinstance(locations, list) else []:
        if not isinstance(entry, Mapping):
            continue
        # A location can also be on-site/hybrid; only remote-allowed countries count.
        if _text(entry.get("work_arrangement")) not in {None, "remote"}:
            continue
        country = _text(entry.get("country"))
        if country and country not in names:
            names.append(country)
    return names


def _location(countries: list[str]) -> tuple[str | None, RemoteEligibility]:
    if not countries:
        return None, RemoteEligibility.UNKNOWN
    if countries == ["Spain"]:
        return "Remote — Spain", RemoteEligibility.SPAIN_ONLY
    text = "Remote — " + ", ".join(countries)
    if len(text) > _LOCATION_LIMIT:
        # Keep Spain visible when eligible so the geography check stays explicit.
        shown = ["Spain"] if "Spain" in countries else countries[:5]
        text = f"Remote — {', '.join(shown)} (+{len(countries) - len(shown)} more countries)"
    return text, RemoteEligibility.COUNTRY_RESTRICTED


def _https_url(value: Any) -> str | None:
    text = _text(value)
    return text if text is not None and text.startswith("https://") and len(text) <= 2048 else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
