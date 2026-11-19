"""JobSearch from Sweden's Public Employment Service (public, CC0 job ads)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ai_job_hunter.connectors._portal_http import get_json, new_client
from ai_job_hunter.domain.normalized_job import NormalizedJob

API_URL = "https://jobsearch.api.jobtechdev.se/search"
_QUERIES = ("backend", "systemutvecklare", "mjukvaruutvecklare")


class JobTechConnectorError(RuntimeError):
    """A safe, user-readable portal failure."""


class JobTechConnector:
    provider = "jobtech"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or new_client(self._timeout)
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        try:
            for query in _QUERIES:
                payload = get_json(
                    client, API_URL, {"q": query, "limit": 50, "sort": "pubdate-desc", "published-after": 7 * 24 * 60},
                    portal="JobTech JobSearch", error=JobTechConnectorError, timeout=self._timeout,
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
                    raise JobTechConnectorError("JobTech JobSearch returned an unexpected payload.")
                for raw in payload["hits"]:
                    if not isinstance(raw, dict) or raw.get("removed") is True:
                        continue
                    try:
                        job = _normalize_job(raw, discovered_at)
                    except ValueError:
                        continue
                    if job.external_id is not None:
                        jobs.setdefault(job.external_id, job)
        finally:
            if self._client is None:
                client.close()
        return list(jobs.values())


def _normalize_job(raw: Mapping[str, Any], discovered_at: datetime) -> NormalizedJob:
    job_id = _text(raw.get("id"))
    title = _text(raw.get("headline"))
    parts = urlsplit(_text(raw.get("webpage_url")) or "")
    if (
        not job_id or not job_id.isascii() or not job_id.isdecimal() or not title
        or parts.scheme != "https" or parts.netloc not in {"arbetsformedlingen.se", "www.arbetsformedlingen.se"}
        or parts.path.rstrip("/") != f"/platsbanken/annonser/{job_id}"
    ):
        raise ValueError("title, ID and matching Platsbanken URL are required")
    url = f"https://arbetsformedlingen.se/platsbanken/annonser/{job_id}"

    employer = raw.get("employer")
    address = raw.get("workplace_address")
    description = raw.get("description")
    company = _text(employer.get("name")) if isinstance(employer, dict) else None
    location = _location(address) if isinstance(address, dict) else None
    return NormalizedJob(
        provider=JobTechConnector.provider,
        external_id=job_id,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title[:255],
        company_name=company[:255] if company else None,
        description=_text(description.get("text")) if isinstance(description, dict) else None,
        location=location,
        published_at=_published_at(raw.get("publication_date")),
        discovered_at=discovered_at,
    )


def _location(address: Mapping[str, Any]) -> str | None:
    city = _text(address.get("city")) or _text(address.get("municipality"))
    country = _text(address.get("country"))
    if country and country.casefold() == "sverige":
        country = "Sweden"
    return ", ".join(part for part in (city, country) if part)[:255] or None


def _published_at(value: Any) -> datetime | None:
    text = _text(value)
    if not text or "T" not in text:
        return None
    try:
        date = datetime.fromisoformat(text)
        # JobSearch emits Swedish local time when there is no offset.
        if date.tzinfo is None:
            date = date.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
        return date.astimezone(UTC)
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        return None


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None
