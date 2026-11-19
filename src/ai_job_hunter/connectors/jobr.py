"""Jobr's public country-filtered XML feed (https://jobr.pro/job-feed)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from itertools import islice
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import USER_AGENT, get_xml
from ai_job_hunter.domain.normalized_job import NormalizedJob, RemoteEligibility, RemotePolicy

FEED_URL = "https://jobr.pro/feed.xml"
_COUNTRIES = ("ES", "IE", "NL", "CH", "GB")
_LIMIT = 50
_REMOTE_POLICIES = {
    "hybrid": RemotePolicy.HYBRID,
    "fully_remote": RemotePolicy.REMOTE,
    "remote_country": RemotePolicy.REMOTE,
    "remote_region": RemotePolicy.REMOTE,
}


class JobrConnectorError(RuntimeError):
    """A safe, user-readable portal failure."""


class JobrConnector:
    provider = "jobr"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        try:
            for country in _COUNTRIES:
                root = get_xml(
                    client, FEED_URL, params={"role": "Software Engineer", "location": country, "limit": _LIMIT},
                    portal="Jobr", error=JobrConnectorError, timeout=self._timeout, strip_utf8_controls=True,
                )
                if root.tag != "jobs":
                    raise JobrConnectorError("Jobr returned an unexpected feed.")
                for item in islice(root.iterfind("job"), _LIMIT):
                    try:
                        job = _normalize_item(item, discovered_at)
                    except ValueError:
                        continue
                    if job.external_id is not None:
                        jobs.setdefault(job.external_id, job)
        finally:
            if self._client is None:
                client.close()
        return list(jobs.values())


def _normalize_item(item: Element, discovered_at: datetime) -> NormalizedJob:
    job_id = (item.findtext("id") or "").strip()
    title = (item.findtext("title") or "").strip()
    url = (item.findtext("jobUrl") or "").strip()
    parts = urlsplit(url)
    if (
        not title or not re.fullmatch(r"[0-9]{1,32}", job_id) or len(url) > 2048
        or parts.scheme != "https" or parts.netloc != "jobr.pro"
        or not re.fullmatch(rf"/job/{job_id}/[a-z0-9-]+/?", parts.path)
    ):
        raise ValueError("title, ID and matching Jobr URL are required")

    remote = item.find("remote")
    remote_type = remote.get("type") if remote is not None and (remote.text or "").strip() == "true" else None
    eligibility = (
        RemoteEligibility.COUNTRY_RESTRICTED
        if remote_type in {"remote_country", "remote_region"} else RemoteEligibility.UNKNOWN
    )
    location = (item.findtext("location") or "").strip()
    company = (item.findtext("company/name") or "").strip()
    salary_min, salary_max, currency = _salary(item.find("salary"))
    return NormalizedJob(
        provider=JobrConnector.provider,
        external_id=job_id,
        source_url=url,
        canonical_url=parts._replace(query="", fragment="").geturl(),
        apply_url=url,
        title=title[:255],
        company_name=company[:255] or None,
        description=html_to_text(item.findtext("description")),
        location=location if 0 < len(location) <= 255 else None,
        remote_policy=_REMOTE_POLICIES.get(remote_type) if remote_type else None,
        remote_eligibility=eligibility,
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        published_at=_published_at(item.findtext("datePosted")),
        discovered_at=discovered_at,
    )


def _salary(field: Element | None) -> tuple[Decimal | None, Decimal | None, str | None]:
    if field is None:
        return None, None, None
    currency = field.get("currency", "").strip().upper()
    lower, upper = (_amount(field.findtext(tag)) for tag in ("min", "max"))
    if not re.fullmatch(r"[A-Z]{3}", currency) or (lower is None and upper is None):
        return None, None, None
    if lower is not None and upper is not None and lower > upper:
        return None, None, None
    return lower, upper, currency


def _amount(raw: str | None) -> Decimal | None:
    value = (raw or "").strip()
    if not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", value):
        return None
    return Decimal(value) or None


def _published_at(raw: str | None) -> datetime | None:
    try:
        date = datetime.fromisoformat((raw or "").strip())
    except ValueError:
        return None
    return date if date.tzinfo else None
