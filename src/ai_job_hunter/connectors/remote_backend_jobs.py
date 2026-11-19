"""Remote Backend Jobs' public RSS feed (https://www.remotebackendjobs.com/developers)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import USER_AGENT, get_rss
from ai_job_hunter.domain.normalized_job import NormalizedJob, RemoteEligibility, RemotePolicy

FEED_URL = "https://www.remotebackendjobs.com/feed.xml"
_DETAILS = re.compile(r"^<p>Location:\s*(.*?)(?: · Salary:.*?)?</p>", re.DOTALL)


class RemoteBackendJobsConnectorError(RuntimeError):
    """A safe, user-readable portal failure."""


class RemoteBackendJobsConnector:
    provider = "remote_backend_jobs"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"},
        )
        try:
            root = get_rss(
                client, FEED_URL, portal="Remote Backend Jobs", error=RemoteBackendJobsConnectorError,
                timeout=self._timeout,
            )
        finally:
            if self._client is None:
                client.close()
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        for item in root.iterfind("./channel/item"):
            try:
                job = _normalize_item(item, discovered_at)
            except ValueError:
                continue
            if job.external_id is not None:
                jobs.setdefault(job.external_id, job)
        return list(jobs.values())


def _normalize_item(item: Element, discovered_at: datetime) -> NormalizedJob:
    raw_title = (item.findtext("title") or "").strip()
    url = (item.findtext("link") or "").strip()
    parts = urlsplit(url)
    match = re.fullmatch(r"/([a-z0-9]{16,40})(?:-[a-z0-9-]+)?/?", parts.path)
    if (
        not raw_title or len(url) > 2048 or not match or parts.scheme != "https"
        or parts.netloc != "www.remotebackendjobs.com"
    ):
        raise ValueError("title and Remote Backend Jobs listing URL are required")

    title, separator, company = raw_title.rpartition(" at ")
    if not separator or not title.strip() or not company.strip():
        title, company = raw_title, ""
    body = (item.findtext("description") or "").lstrip()
    details = _DETAILS.match(body)
    location = html_to_text(details[1]) if details else None
    if details:
        body = body[details.end():]
    eligibility = (
        RemoteEligibility.WORLDWIDE
        if location and location.casefold() in {"worldwide", "anywhere in the world"} else RemoteEligibility.UNKNOWN
    )
    # Make a region in the RSS location actionable without treating it as a worldwide job.
    if location and not re.search(r"\bremote\b", location, re.IGNORECASE):
        location = f"Remote, {location}"
    return NormalizedJob(
        provider=RemoteBackendJobsConnector.provider,
        external_id=match[1],
        source_url=url,
        canonical_url=parts._replace(query="", fragment="").geturl(),
        apply_url=url,
        title=title[:255],
        company_name=company[:255] or None,
        description=html_to_text(body),
        location=location if location and len(location) <= 255 else None,
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=eligibility,
        published_at=_published_at(item.findtext("pubDate")),
        discovered_at=discovered_at,
    )


def _published_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        date = parsedate_to_datetime(raw)
    except ValueError:
        return None
    return date if date.tzinfo else None
