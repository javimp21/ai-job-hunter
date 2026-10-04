"""We Work Remotely public category RSS feeds.

The feeds are the ones the site publishes per category (robots.txt allows
them; `ttl` is 60 minutes). Alerts credit We Work Remotely and link to the
listing, which leads to the application. `region` is "Anywhere in the World"
or a restriction such as "North America Only"; `country` (when present) is the
list of eligible countries. Only an unrestricted "Anywhere" without a country
list is mapped to WORLDWIDE; everything else is a country restriction whose
text stays in `location` for the geography check.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import USER_AGENT
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemoteEligibility, RemotePolicy

FEED_URL = "https://weworkremotely.com/categories/{category}.rss"
DEFAULT_CATEGORIES = (
    "remote-back-end-programming-jobs",
    "remote-full-stack-programming-jobs",
    "remote-devops-sysadmin-jobs",
)
_MAX_FEED_BYTES = 4_000_000
_LOCATION_LIMIT = 255
_FLAGS = re.compile("[\U0001f1e6-\U0001f1ff]")
_EMPLOYMENT_TYPES = {
    "full-time": EmploymentType.FULL_TIME,
    "part-time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "internship": EmploymentType.INTERNSHIP,
}


class WeWorkRemotelyConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only)."""


class WeWorkRemotelyConnector:
    provider = "weworkremotely"

    def __init__(
        self,
        *,
        categories: tuple[str, ...] = DEFAULT_CATEGORIES,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
        pause_seconds: float = 2.0,
    ) -> None:
        self.categories = categories
        self._client = client
        self._timeout = timeout
        self._pause = pause_seconds

    def fetch_jobs(self) -> list[NormalizedJob]:
        client = self._client or httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"},
        )
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        try:
            for index, category in enumerate(self.categories):
                if index:
                    time.sleep(self._pause)
                root = _parse_feed(self._get(client, category))
                for item in root.iterfind("./channel/item"):
                    try:
                        job = _normalize_item(item, discovered_at=discovered_at)
                    except ValueError:
                        continue
                    jobs.setdefault(job.external_id or job.source_url or job.title, job)
        finally:
            if self._client is None:
                client.close()
        return list(jobs.values())

    def _get(self, client: httpx.Client, category: str) -> bytes:
        try:
            response = client.get(FEED_URL.format(category=category), timeout=self._timeout)
        except httpx.HTTPError as error:
            raise WeWorkRemotelyConnectorError(f"We Work Remotely request failed ({type(error).__name__}).") from None
        if response.status_code != 200:
            raise WeWorkRemotelyConnectorError(f"We Work Remotely returned HTTP {response.status_code}.")
        return response.content


def _parse_feed(content: bytes) -> ElementTree.Element:
    if len(content) > _MAX_FEED_BYTES:
        raise WeWorkRemotelyConnectorError("We Work Remotely feed is too large.")
    # Entity expansion needs a DTD; refuse any document that declares one.
    probe = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise WeWorkRemotelyConnectorError("We Work Remotely feed contains a forbidden DTD declaration.")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        raise WeWorkRemotelyConnectorError("We Work Remotely feed is not valid XML.") from None
    if root.tag != "rss":
        raise WeWorkRemotelyConnectorError("We Work Remotely feed is not an RSS document.")
    return root


def _normalize_item(item: ElementTree.Element, *, discovered_at: datetime) -> NormalizedJob:
    link = _child(item, "link") or _child(item, "guid")
    raw_title = _child(item, "title")
    if link is None or raw_title is None:
        raise ValueError("title and link are required")
    parts = urlsplit(link)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in {"weworkremotely.com", "www.weworkremotely.com"} or not parts.path.startswith(
        "/remote-jobs/"
    ):
        raise ValueError("link must be a We Work Remotely listing")
    # Titles read "Company: Role"; a title without that separator has no reliable company.
    company, separator, title = raw_title.partition(": ")
    if not separator or not title.strip():
        company, title = None, raw_title
    region = _child(item, "region")
    countries = _countries(_child(item, "country"))
    location, eligibility = _location(region, countries)
    return NormalizedJob(
        provider=WeWorkRemotelyConnector.provider,
        external_id=parts.path.rsplit("/", 1)[-1],
        source_url=link,
        canonical_url=link,
        apply_url=link,
        title=title.strip()[:255],
        company_name=company.strip()[:255] if company else None,
        description=html_to_text(_child(item, "description")),
        location=location,
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=eligibility,
        employment_type=_EMPLOYMENT_TYPES.get((_child(item, "type") or "").casefold()),
        published_at=_timestamp(_child(item, "pubDate")),
        discovered_at=discovered_at,
        raw_metadata={
            key: value
            for key, value in {
                "region": region,
                "countries": countries or None,
                "category": _child(item, "category"),
                "skills": _child(item, "skills"),
                "expires_at": _child(item, "expires_at"),
            }.items()
            if value
        },
    )


def _countries(text: str | None) -> list[str]:
    if not text:
        return []
    names = []
    for part in _FLAGS.sub("", text).split(","):
        name = part.strip()
        if name.casefold().startswith("and "):
            name = name[4:].strip()
        if name:
            names.append(name)
    return names


def _location(region: str | None, countries: list[str]) -> tuple[str | None, RemoteEligibility]:
    if countries:
        text = "Remote — " + ", ".join(countries)
        if len(text) > _LOCATION_LIMIT:
            # Keep Spain visible when eligible so the geography check stays explicit.
            shown = ["Spain"] if "Spain" in countries else countries[:5]
            text = f"Remote — {', '.join(shown)} (+{len(countries) - len(shown)} more countries)"
        return text, RemoteEligibility.COUNTRY_RESTRICTED
    if region is None:
        return None, RemoteEligibility.UNKNOWN
    if region.casefold() in {"anywhere in the world", "anywhere", "worldwide"}:
        return "Remote — Worldwide", RemoteEligibility.WORLDWIDE
    return f"Remote — {region}"[:_LOCATION_LIMIT], RemoteEligibility.COUNTRY_RESTRICTED


def _child(item: ElementTree.Element, tag: str) -> str | None:
    node = item.find(tag)
    text = node.text.strip() if node is not None and node.text else ""
    return text or None


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None
