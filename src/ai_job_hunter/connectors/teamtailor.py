"""Read and normalize public Teamtailor career-site RSS feeds."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import NormalizedJob, RemotePolicy

TEAMTAILOR_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_COMPANY_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})$")
_MAX_FEED_BYTES = 20 * 1024 * 1024
_LOCATIONS_NAMESPACE = "https://teamtailor.com/locations"
# Observed values on a live feed: "hybrid" and "none". "fully" and "temporary" are
# the other documented values; anything else stays unknown.
_REMOTE_STATUS = {
    "fully": RemotePolicy.REMOTE,
    "hybrid": RemotePolicy.HYBRID,
    "none": RemotePolicy.ONSITE,
}


class TeamtailorConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Teamtailor job feed."""


class TeamtailorConnector:
    """Fetch publicly published jobs from ``{company}.teamtailor.com/jobs.rss``."""

    provider = "teamtailor"

    def __init__(
        self,
        company: str,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        normalized = company.strip()
        if not normalized:
            raise ValueError("company must not be empty")
        if not _COMPANY_SLUG.fullmatch(normalized):
            raise ValueError("company must be a Teamtailor subdomain label")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.company = normalized
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def feed_url(self) -> str:
        return f"https://{self.company}.teamtailor.com/jobs.rss"

    def fetch_jobs(self) -> list[NormalizedJob]:
        headers = {
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.1",
            "User-Agent": TEAMTAILOR_USER_AGENT,
        }
        try:
            response = self._client.get(self.feed_url, headers=headers)
        except httpx.RequestError as error:
            raise TeamtailorConnectorError("Could not reach the Teamtailor job feed.") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise TeamtailorConnectorError(
                f"Teamtailor job feed returned HTTP {error.response.status_code}."
            ) from error
        root = _parse_feed(response.content)
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, item in enumerate(root.iter("item")):
            if self.max_jobs is not None and len(offers) >= self.max_jobs:
                break
            try:
                offers.append(
                    _normalize_item(item, company_name=self.company_name, discovered_at=discovered_at)
                )
            except (TypeError, ValueError) as error:
                raise TeamtailorConnectorError(
                    f"Teamtailor item at position {index} does not match public feed fields."
                ) from error
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TeamtailorConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _parse_feed(content: bytes) -> ElementTree.Element:
    if len(content) > _MAX_FEED_BYTES:
        raise TeamtailorConnectorError("Teamtailor job feed is too large.")
    # Entity expansion needs a DTD; refuse any document that declares one.
    # Null bytes are stripped so UTF-16 encoded declarations are also caught.
    probe = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise TeamtailorConnectorError("Teamtailor job feed contains a forbidden DTD declaration.")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise TeamtailorConnectorError("Teamtailor job feed is not valid XML.") from error
    if root.tag != "rss":
        raise TeamtailorConnectorError("Teamtailor job feed is not an RSS document.")
    return root


def _normalize_item(
    item: ElementTree.Element, *, company_name: str | None, discovered_at: datetime
) -> NormalizedJob:
    title = _child_text(item, "title")
    if title is None:
        raise ValueError("title is required")
    link = _child_text(item, "link")
    guid = _child_text(item, "guid")
    remote_status = _child_text(item, "remoteStatus")
    locations = _locations(item)
    location = "; ".join(locations) or None
    if location is not None and len(location) > 255:
        location = None
    return NormalizedJob(
        provider=TeamtailorConnector.provider,
        external_id=guid or link,
        source_url=link,
        canonical_url=link,
        apply_url=link,
        title=title,
        company_name=company_name,
        description=html_to_text(_child_text(item, "description")),
        location=location,
        remote_policy=_REMOTE_STATUS.get(remote_status.casefold()) if remote_status else None,
        # The office country is not a list of countries remote work is allowed from,
        # so remote_eligibility keeps its UNKNOWN default.
        published_at=_parse_pub_date(_child_text(item, "pubDate")),
        raw_metadata={
            "title": title,
            "link": link,
            "guid": guid,
            "remoteStatus": remote_status,
            "department": _child_text(item, "department", _LOCATIONS_NAMESPACE),
            "role": _child_text(item, "role", _LOCATIONS_NAMESPACE),
            "locations": locations,
        },
        discovered_at=discovered_at,
    )


def _locations(item: ElementTree.Element) -> list[str]:
    result: list[str] = []
    for node in item.iter(f"{{{_LOCATIONS_NAMESPACE}}}location"):
        city = _child_text(node, "city", _LOCATIONS_NAMESPACE)
        country = _child_text(node, "country", _LOCATIONS_NAMESPACE)
        name = _child_text(node, "name", _LOCATIONS_NAMESPACE)
        text = ", ".join(part for part in (city, country) if part) or name
        if text and text not in result:
            result.append(text)
    return result


def _child_text(node: ElementTree.Element, tag: str, namespace: str | None = None) -> str | None:
    child = node.find(f"{{{namespace}}}{tag}" if namespace else tag)
    return _optional_text(child.text) if child is not None else None


def _parse_pub_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
