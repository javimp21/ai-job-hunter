"""Remote OK public JSON feed (https://remoteok.com/api).

The first array element is a legal notice, not a job. Remote OK's terms
require linking back to the job on remoteok.com and naming Remote OK as the
source, so `apply_url` is the Remote OK listing (not its redirecting
`apply_url`) and alerts show a credit. The feed has no structured
eligibility: only an explicit "worldwide" location is mapped; any other text
stays in `location` for the geography check.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import get_json, new_client
from ai_job_hunter.domain.normalized_job import NormalizedJob, RemoteEligibility, RemotePolicy, SalaryPeriod

API_URL = "https://remoteok.com/api"
_WORLDWIDE = {"worldwide", "anywhere", "global", "remote", "anywhere in the world"}


class RemoteOKConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only)."""


class RemoteOKConnector:
    provider = "remoteok"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or new_client(self._timeout)
        try:
            payload = get_json(
                client, API_URL, None, portal="Remote OK", error=RemoteOKConnectorError, timeout=self._timeout
            )
        finally:
            if self._client is None:
                client.close()
        if not isinstance(payload, list):
            raise RemoteOKConnectorError("Remote OK returned an unexpected payload.")
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        for raw in payload:
            # The legal notice (and anything else without a position) is skipped.
            if not isinstance(raw, Mapping) or "legal" in raw or not raw.get("position"):
                continue
            try:
                job = _normalize_job(raw, discovered_at=discovered_at)
            except ValueError:
                continue
            jobs.setdefault(job.external_id or job.source_url or job.title, job)
        return list(jobs.values())


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("position"))
    url = _text(raw.get("url"))
    if title is None or url is None:
        raise ValueError("position and url are required")
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in {"remoteok.com", "www.remoteok.com"}:
        raise ValueError("url must be a Remote OK listing")
    raw_id = raw.get("id")
    location = _text(raw.get("location"))
    worldwide = location is not None and location.casefold() in _WORLDWIDE
    salary_min = _decimal(raw.get("salary_min"))
    salary_max = _decimal(raw.get("salary_max"))
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        salary_min = salary_max = None
    has_salary = salary_min is not None or salary_max is not None
    return NormalizedJob(
        provider=RemoteOKConnector.provider,
        external_id=str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title,
        company_name=_text(raw.get("company")),
        description=html_to_text(_text(raw.get("description"))),
        location="Remote — Worldwide" if worldwide else location,
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=RemoteEligibility.WORLDWIDE if worldwide else RemoteEligibility.UNKNOWN,
        salary_min=salary_min,
        salary_max=salary_max,
        # Remote OK quotes yearly USD ranges; 0 means "not given".
        currency="USD" if has_salary else None,
        salary_period=SalaryPeriod.YEAR if has_salary else None,
        published_at=_timestamp(raw.get("date")),
        discovered_at=discovered_at,
        raw_metadata={key: value for key, value in raw.items() if key not in {"description", "apply_url"}},
    )


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
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
