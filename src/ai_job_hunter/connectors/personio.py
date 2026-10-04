"""Read and normalize public Personio career-site XML feeds."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from typing import Any

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob

PERSONIO_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
PERSONIO_REGIONS = frozenset({"de", "com"})
_COMPANY_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})$")
_MAX_FEED_BYTES = 20 * 1024 * 1024
# Only unambiguous schedules are mapped; "full-or-part-time" stays unknown.
_SCHEDULES = {"full-time": EmploymentType.FULL_TIME, "part-time": EmploymentType.PART_TIME}


class PersonioConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Personio job feed."""


class PersonioConnector:
    """Fetch publicly published jobs from ``{company}.jobs.personio.{de|com}/xml``."""

    provider = "personio"

    def __init__(
        self,
        company: str,
        *,
        company_name: str | None = None,
        region: str = "de",
        max_jobs: int | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        normalized = company.strip()
        if not normalized:
            raise ValueError("company must not be empty")
        if not _COMPANY_SLUG.fullmatch(normalized):
            raise ValueError("company must be a Personio subdomain label")
        region = region.strip().casefold()
        if region not in PERSONIO_REGIONS:
            raise ValueError("region must be 'de' or 'com'")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.company = normalized
        self.region = region
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def base_url(self) -> str:
        return f"https://{self.company}.jobs.personio.{self.region}"

    def fetch_jobs(self) -> list[NormalizedJob]:
        headers = {
            "Accept": "application/xml, text/xml;q=0.9, */*;q=0.1",
            "User-Agent": PERSONIO_USER_AGENT,
        }
        try:
            response = self._client.get(f"{self.base_url}/xml", headers=headers)
        except httpx.RequestError as error:
            raise PersonioConnectorError("Could not reach the Personio job feed.") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise PersonioConnectorError(
                f"Personio job feed returned HTTP {error.response.status_code}."
            ) from error
        root = _parse_feed(response.content)
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, position in enumerate(root.findall("position")):
            if self.max_jobs is not None and len(offers) >= self.max_jobs:
                break
            try:
                offers.append(
                    _normalize_position(
                        position,
                        base_url=self.base_url,
                        company_name=self.company_name,
                        discovered_at=discovered_at,
                    )
                )
            except (TypeError, ValueError) as error:
                raise PersonioConnectorError(
                    f"Personio position at index {index} does not match public feed fields."
                ) from error
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> PersonioConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _parse_feed(content: bytes) -> ElementTree.Element:
    if len(content) > _MAX_FEED_BYTES:
        raise PersonioConnectorError("Personio job feed is too large.")
    # Entity expansion needs a DTD; refuse any document that declares one.
    # Null bytes are stripped so UTF-16 encoded declarations are also caught.
    probe = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise PersonioConnectorError("Personio job feed contains a forbidden DTD declaration.")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise PersonioConnectorError("Personio job feed is not valid XML.") from error
    if root.tag != "workzag-jobs":
        raise PersonioConnectorError("Personio job feed is not a workzag-jobs document.")
    return root


def _normalize_position(
    position: ElementTree.Element,
    *,
    base_url: str,
    company_name: str | None,
    discovered_at: datetime,
) -> NormalizedJob:
    title = _child_text(position, "name")
    if title is None:
        raise ValueError("name is required")
    job_id = _child_text(position, "id")
    url = f"{base_url}/job/{job_id}" if job_id else None
    offices: list[str] = []
    for text in [_child_text(position, "office")] + [
        _optional_text(node.text) for node in position.findall("additionalOffices/office")
    ]:
        if text and text not in offices:
            offices.append(text)
    location = "; ".join(offices) or None
    if location is not None and len(location) > 255:
        location = None
    schedule = _child_text(position, "schedule")
    return NormalizedJob(
        provider=PersonioConnector.provider,
        external_id=job_id,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title,
        company_name=company_name,
        description=_description(position),
        location=location,
        # The feed carries no work-mode field, so remote_policy and remote_eligibility stay unknown.
        employment_type=_SCHEDULES.get(schedule.casefold()) if schedule else None,
        published_at=_parse_datetime(_child_text(position, "createdAt")),
        raw_metadata={
            "id": job_id,
            "subcompany": _child_text(position, "subcompany"),
            "department": _child_text(position, "department"),
            "recruitingCategory": _child_text(position, "recruitingCategory"),
            "employmentType": _child_text(position, "employmentType"),
            "schedule": schedule,
            "seniority": _child_text(position, "seniority"),
            "yearsOfExperience": _child_text(position, "yearsOfExperience"),
            "occupation": _child_text(position, "occupation"),
            "offices": offices,
        },
        discovered_at=discovered_at,
    )


def _description(position: ElementTree.Element) -> str | None:
    sections: list[str] = []
    for node in position.findall("jobDescriptions/jobDescription"):
        heading = _child_text(node, "name")
        body = html_to_text(_child_text(node, "value"))
        if body is None:
            continue
        sections.append(f"{heading}\n{body}" if heading else body)
    return "\n\n".join(sections) or None


def _child_text(node: ElementTree.Element, tag: str) -> str | None:
    child = node.find(tag)
    return _optional_text(child.text) if child is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
