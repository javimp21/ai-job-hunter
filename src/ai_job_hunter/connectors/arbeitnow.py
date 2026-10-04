"""Arbeitnow free job-board API (https://www.arbeitnow.com/api/job-board-api).

Arbeitnow's terms (section 11) allow API use if the platform links back to
Arbeitnow.com, so alerts show a credit and `apply_url` is the Arbeitnow
listing. The feed is mostly Germany/EU on-site roles and is refreshed hourly;
only the first page (newest first) is read. Nothing is filtered here beyond
the API's own `remote` flag being recorded: `remote: true` is REMOTE, while
`remote: false` only means "not marked remote" and leaves the work mode
unknown. `location` is free text, so eligibility stays UNKNOWN and the
existing prefilter decides.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import get_json, new_client
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemoteEligibility, RemotePolicy

API_URL = "https://www.arbeitnow.com/api/job-board-api"
# The feed also lists Arbeitnow's country mirrors (seen live: 100 .com, 75 each .co.uk/.fr/.ch).
_LISTING_HOSTS = {f"{prefix}arbeitnow.{tld}" for prefix in ("", "www.") for tld in ("com", "co.uk", "fr", "ch")}


class ArbeitnowConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only)."""


class ArbeitnowConnector:
    provider = "arbeitnow"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or new_client(self._timeout)
        try:
            payload = get_json(
                client, API_URL, None, portal="Arbeitnow", error=ArbeitnowConnectorError, timeout=self._timeout
            )
        finally:
            if self._client is None:
                client.close()
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            raise ArbeitnowConnectorError("Arbeitnow returned an unexpected payload.")
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        for raw in payload["data"]:
            if not isinstance(raw, Mapping):
                continue
            try:
                job = _normalize_job(raw, discovered_at=discovered_at)
            except ValueError:
                continue
            jobs.setdefault(job.external_id or job.source_url or job.title, job)
        return list(jobs.values())


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("title"))
    url = _text(raw.get("url"))
    if title is None or url is None:
        raise ValueError("title and url are required")
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in _LISTING_HOSTS:
        raise ValueError("url must be an Arbeitnow listing")
    location = _text(raw.get("location"))
    remote = raw.get("remote") is True
    return NormalizedJob(
        provider=ArbeitnowConnector.provider,
        external_id=_text(raw.get("slug")),
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title[:255],
        company_name=(_text(raw.get("company_name")) or "")[:255] or None,
        description=html_to_text(_text(raw.get("description"))),
        location=location[:255] if location else None,
        remote_policy=RemotePolicy.REMOTE if remote else None,
        remote_eligibility=RemoteEligibility.UNKNOWN,
        employment_type=_employment_type(raw.get("job_types")),
        published_at=_timestamp(raw.get("created_at")),
        discovered_at=discovered_at,
        raw_metadata={key: value for key, value in raw.items() if key != "description"},
    )


def _employment_type(value: Any) -> EmploymentType | None:
    types = {item.casefold().replace(" ", "").replace("-", "") for item in value if isinstance(item, str)} if isinstance(value, list) else set()
    if types & {"fulltime", "fulltimepermanent"}:
        return EmploymentType.FULL_TIME
    if "parttime" in types:
        return EmploymentType.PART_TIME
    return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None
