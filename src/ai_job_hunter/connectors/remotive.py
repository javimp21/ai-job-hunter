"""Read and normalize job listings from Remotive's public JSON API."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)

LOGGER = logging.getLogger(__name__)
REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
REMOTIVE_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"

_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "ul",
}
_JOB_TYPES = {
    "full_time": EmploymentType.FULL_TIME,
    "part_time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "internship": EmploymentType.INTERNSHIP,
    "freelance": EmploymentType.OTHER,
    "other": EmploymentType.OTHER,
}
_CURRENCY_PATTERNS = (
    ("USD", re.compile(r"\bUSD\b|US\$", re.IGNORECASE)),
    ("EUR", re.compile(r"\bEUR\b|€", re.IGNORECASE)),
    ("GBP", re.compile(r"\bGBP\b|£", re.IGNORECASE)),
    ("CAD", re.compile(r"\bCAD\b|C\$", re.IGNORECASE)),
    ("AUD", re.compile(r"\bAUD\b|A\$", re.IGNORECASE)),
    ("NZD", re.compile(r"\bNZD\b|NZ\$", re.IGNORECASE)),
)
_SALARY_AMOUNT = re.compile(
    r"(?<![\w.])(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<scale>\s*[kKmM])?(?![\w.])"
)
_SALARY_PERIODS = (
    (
        SalaryPeriod.HOUR,
        re.compile(r"\b(?:per\s+hour|hourly|/\s*hour)\b", re.IGNORECASE),
    ),
    (
        SalaryPeriod.DAY,
        re.compile(r"\b(?:per\s+day|daily|/\s*day)\b", re.IGNORECASE),
    ),
    (
        SalaryPeriod.WEEK,
        re.compile(r"\b(?:per\s+week|weekly|/\s*week)\b", re.IGNORECASE),
    ),
    (
        SalaryPeriod.MONTH,
        re.compile(r"\b(?:per\s+month|monthly|/\s*month)\b", re.IGNORECASE),
    ),
    (
        SalaryPeriod.YEAR,
        re.compile(r"\b(?:per\s+year|yearly|annual(?:ly)?|/\s*year)\b", re.IGNORECASE),
    ),
)


class RemotiveConnectorError(RuntimeError):
    """An HTTP or payload error while reading Remotive's public API."""


class _DescriptionTextParser(HTMLParser):
    """Extract readable text while keeping block boundaries and skipping scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipped_tags: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skipped_tags.append(tag)
        elif not self.skipped_tags and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            if tag in self.skipped_tags:
                self.skipped_tags.remove(tag)
        elif not self.skipped_tags and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipped_tags:
            self.parts.append(data)


class RemotiveConnector:
    """Fetch one Remotive API response and return normalized job records.

    The API has no page parameter. ``limit`` and the optional source-level
    filters are sent as documented query parameters. The connector deliberately
    does not retry requests; callers should respect Remotive's low request rate.
    """

    provider = "remotive"

    def __init__(
        self,
        *,
        limit: int | None = None,
        search: str | None = None,
        category: str | None = None,
        company_name: str | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        if limit is not None and limit < 1:
            raise ValueError("limit must be a positive integer")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        self._params: dict[str, str | int] = {}
        self._limit = limit
        for key, value in (
            ("search", search),
            ("category", category),
            ("company_name", company_name),
        ):
            if value is not None and value.strip():
                self._params[key] = value.strip()
        if limit is not None:
            self._params["limit"] = limit

        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": REMOTIVE_USER_AGENT,
            },
        )

    def fetch_jobs(self) -> list[NormalizedJob]:
        """Fetch, validate, and normalize one response from Remotive."""

        try:
            response = self._client.get(
                REMOTIVE_API_URL,
                params=self._params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": REMOTIVE_USER_AGENT,
                },
            )
        except httpx.RequestError as error:
            raise RemotiveConnectorError("Could not reach the Remotive API.") from error

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RemotiveConnectorError(
                f"Remotive API returned HTTP {error.response.status_code}."
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            raise RemotiveConnectorError("Remotive API returned invalid JSON.") from error

        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise RemotiveConnectorError("Remotive API response must contain a jobs list.")

        raw_jobs = payload["jobs"]
        selected_jobs = raw_jobs if self._limit is None else raw_jobs[: self._limit]
        if self._limit is not None and len(raw_jobs) > self._limit:
            LOGGER.warning(
                "Remotive returned %d jobs for limit=%d; processing only the first %d",
                len(raw_jobs),
                self._limit,
                self._limit,
            )

        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, raw_job in enumerate(selected_jobs):
            if not isinstance(raw_job, dict):
                raise RemotiveConnectorError(
                    f"Remotive API job at index {index} is not a JSON object."
                )
            try:
                offers.append(_normalize_job(raw_job, discovered_at=discovered_at))
            except (TypeError, ValueError) as error:
                raise RemotiveConnectorError(
                    f"Remotive API job at index {index} does not match the documented fields."
                ) from error

        return offers

    def close(self) -> None:
        """Close the HTTP client when this connector created it."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> RemotiveConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_job(raw_job: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _required_text(raw_job, "title")
    source_url = _required_text(raw_job, "url")
    parsed_source_url = urlsplit(source_url)
    if (
        parsed_source_url.scheme.lower() != "https"
        or parsed_source_url.hostname is None
        or parsed_source_url.hostname.lower() not in {"remotive.com", "www.remotive.com"}
    ):
        raise ValueError("url must be a Remotive listing URL")

    raw_id = raw_job.get("id")
    external_id = (
        str(raw_id)
        if isinstance(raw_id, (str, int))
        and not isinstance(raw_id, bool)
        and str(raw_id).strip()
        else None
    )
    location = _optional_text(raw_job.get("candidate_required_location"))
    salary_min, salary_max, currency, salary_period = _parse_salary(raw_job.get("salary"))
    employment_value = _optional_text(raw_job.get("job_type"))
    employment_type = (
        _JOB_TYPES.get(employment_value.casefold().replace("-", "_").replace(" ", "_"))
        if employment_value is not None
        else None
    )

    return NormalizedJob(
        provider=RemotiveConnector.provider,
        external_id=external_id,
        source_url=source_url,
        title=title,
        company_name=_bounded_optional_text(raw_job.get("company_name"), 255),
        # The documented API provides a company logo URL, not its website.
        company_website=None,
        description=_html_to_text(_optional_text(raw_job.get("description"))),
        location=_bounded_optional_text(location, 255),
        remote_policy=RemotePolicy.REMOTE,
        remote_eligibility=_remote_eligibility(location),
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_period=salary_period,
        employment_type=employment_type,
        published_at=_parse_published_at(raw_job.get("publication_date")),
        discovered_at=discovered_at,
        # Preserve the original HTML, salary text, logo and undocumented fields.
        raw_metadata=dict(raw_job),
    )


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _bounded_optional_text(value: Any, max_length: int) -> str | None:
    text = _optional_text(value)
    return text if text is not None and len(text) <= max_length else None


def _html_to_text(description: str | None) -> str | None:
    if description is None:
        return None
    parser = _DescriptionTextParser()
    parser.feed(description)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    return text or None


def _remote_eligibility(location: str | None) -> RemoteEligibility:
    normalized = " ".join((location or "").casefold().split())
    if normalized == "worldwide":
        return RemoteEligibility.WORLDWIDE
    if normalized in {"spain", "spain only", "españa", "españa only"}:
        return RemoteEligibility.SPAIN_ONLY
    if normalized:
        # Remotive defines this field as a geographical restriction.
        return RemoteEligibility.COUNTRY_RESTRICTED
    return RemoteEligibility.UNKNOWN


def _parse_published_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    timestamp = value.strip()
    if timestamp.endswith("Z"):
        timestamp = f"{timestamp[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        # The documented example is timezone-naive; retain it in raw_metadata.
        return None
    return parsed.astimezone(UTC)


def _parse_salary(
    value: Any,
) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None, None, None

    currency_matches = {
        currency
        for currency, pattern in _CURRENCY_PATTERNS
        if pattern.search(value)
    }
    # A bare "$" is ambiguous between multiple currencies; keep it only in raw_metadata.
    if len(currency_matches) != 1:
        return None, None, None, None

    amounts = list(_SALARY_AMOUNT.finditer(value))
    if len(amounts) != 2:
        return None, None, None, None
    separator = value[amounts[0].end() : amounts[1].start()]
    separator = re.sub(
        r"\b(?:USD|EUR|GBP|CAD|AUD|NZD)\b|US\$|C\$|A\$|NZ\$|€|£",
        "",
        separator,
        flags=re.IGNORECASE,
    )
    if not re.fullmatch(r"\s*(?:-|–|—|to)\s*", separator, flags=re.IGNORECASE):
        return None, None, None, None

    scales = [
        match.group("scale").strip().casefold() if match.group("scale") else None
        for match in amounts
    ]
    if scales[0] != scales[1]:
        return None, None, None, None
    multiplier = {None: 1, "k": 1_000, "m": 1_000_000}[scales[0]]
    try:
        values = [
            Decimal(match.group("number").replace(",", "")) * multiplier
            for match in amounts
        ]
    except InvalidOperation:
        return None, None, None, None
    if values[0] > values[1]:
        return None, None, None, None

    period = next(
        (salary_period for salary_period, pattern in _SALARY_PERIODS if pattern.search(value)),
        None,
    )
    return values[0], values[1], currency_matches.pop(), period
