"""Python.org's public job-board RSS feed."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import USER_AGENT, get_rss
from ai_job_hunter.domain.normalized_job import NormalizedJob

FEED_URL = "https://www.python.org/jobs/feed/rss/"


class PythonJobsConnectorError(RuntimeError):
    """A safe, user-readable portal failure."""


class PythonJobsConnector:
    provider = "pythonjobs"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"},
        )
        try:
            root = get_rss(
                client, FEED_URL, portal="Python.org Jobs", error=PythonJobsConnectorError, timeout=self._timeout
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


def _normalize_item(item: ElementTree.Element, discovered_at: datetime) -> NormalizedJob:
    raw_title = (item.findtext("title") or "").strip()
    parts = urlsplit((item.findtext("link") or item.findtext("guid") or "").strip())
    match = re.fullmatch(r"/jobs/([0-9]{1,32})/?", parts.path)
    if not raw_title or parts.scheme != "https" or parts.netloc not in {"python.org", "www.python.org"} or not match:
        raise ValueError("title and Python.org job URL are required")
    job_id = match[1]
    url = f"https://www.python.org/jobs/{job_id}/"

    # The feed puts "Title, Company" in <title>, without escaping commas in either field.
    title, separator, company = raw_title.partition(", ")
    if not separator or ", " in company or not title.strip() or not company.strip():
        title, company = raw_title, None
    description = (item.findtext("description") or "").strip()
    location, newline, body = description.partition("\n")
    if not newline or "<" in location or not body.lstrip().startswith("<"):
        location, body = "", description
    return NormalizedJob(
        provider=PythonJobsConnector.provider,
        external_id=job_id,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title[:255],
        company_name=company[:255] if company else None,
        description=html_to_text(body),
        location=html_to_text(location[:255]),
        published_at=_published_at(item.findtext("pubDate")),
        discovered_at=discovered_at,
    )


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        date = parsedate_to_datetime(value)
    except ValueError:
        return None
    return date if date.tzinfo else None
