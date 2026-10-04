"""Read and normalize public Workable job boards through the keyless widget API."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy

WORKABLE_API_BASE = "https://apply.workable.com/api/v1/widget/accounts"
WORKABLE_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_ACCOUNT_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$")
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024
_EMPLOYMENT_TYPES = {
    "full-time": EmploymentType.FULL_TIME,
    "part-time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "internship": EmploymentType.INTERNSHIP,
}


class WorkableConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Workable job board."""


class WorkableConnector:
    """Fetch publicly published jobs from ``apply.workable.com/<account>``."""

    provider = "workable"

    def __init__(
        self,
        account: str,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        normalized = account.strip()
        if not normalized:
            raise ValueError("account must not be empty")
        if not _ACCOUNT_SLUG.fullmatch(normalized):
            raise ValueError("account must be a Workable account slug")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.account = normalized
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_jobs(self) -> list[NormalizedJob]:
        url = f"{WORKABLE_API_BASE}/{quote(self.account, safe='')}"
        try:
            response = self._client.get(
                url,
                params={"details": "true"},
                headers={"Accept": "application/json", "User-Agent": WORKABLE_USER_AGENT},
            )
        except httpx.RequestError as error:
            raise WorkableConnectorError("Could not reach the Workable widget API.") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise WorkableConnectorError(
                f"Workable widget API returned HTTP {error.response.status_code}."
            ) from error
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise WorkableConnectorError("Workable widget API response is too large.")
        try:
            payload = response.json()
        except ValueError as error:
            raise WorkableConnectorError("Workable widget API returned invalid JSON.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise WorkableConnectorError("Workable response must contain a jobs list.")

        board_name = self.company_name or _optional_text(payload.get("name"))
        selected = payload["jobs"] if self.max_jobs is None else payload["jobs"][: self.max_jobs]
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, raw_job in enumerate(selected):
            if not isinstance(raw_job, dict):
                raise WorkableConnectorError(f"Workable job at index {index} is not a JSON object.")
            try:
                offers.append(
                    _normalize_job(raw_job, company_name=board_name, discovered_at=discovered_at)
                )
            except (TypeError, ValueError) as error:
                raise WorkableConnectorError(
                    f"Workable job at index {index} does not match public widget fields."
                ) from error
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> WorkableConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_job(
    raw: Mapping[str, Any], *, company_name: str | None, discovered_at: datetime
) -> NormalizedJob:
    title = _optional_text(raw.get("title"))
    if title is None:
        raise ValueError("title is required")
    url = _optional_text(raw.get("url")) or _optional_text(raw.get("shortlink"))
    shortcode = _optional_text(raw.get("shortcode"))
    locations = _locations(raw)
    location = "; ".join(locations) or None
    if location is not None and len(location) > 255:
        location = None
    employment = _optional_text(raw.get("employment_type"))
    description = raw.get("description")
    return NormalizedJob(
        provider=WorkableConnector.provider,
        external_id=shortcode or url,
        source_url=url,
        canonical_url=url,
        apply_url=_optional_text(raw.get("application_url")) or url,
        title=title,
        company_name=company_name,
        description=html_to_text(description if isinstance(description, str) else None),
        location=location,
        # The widget only exposes a boolean "telecommuting"; False does not mean on-site.
        remote_policy=RemotePolicy.REMOTE if raw.get("telecommuting") is True else None,
        employment_type=_EMPLOYMENT_TYPES.get(employment.casefold()) if employment else None,
        published_at=_parse_date(raw.get("published_on")),
        raw_metadata={
            "shortcode": shortcode,
            "department": _optional_text(raw.get("department")),
            "employment_type": employment,
            "telecommuting": raw.get("telecommuting") if isinstance(raw.get("telecommuting"), bool) else None,
            "experience": _optional_text(raw.get("experience")),
            "locations": locations,
        },
        discovered_at=discovered_at,
    )


def _locations(raw: Mapping[str, Any]) -> list[str]:
    entries = raw.get("locations")
    result: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("hidden") is True:
                continue
            text = ", ".join(
                part for part in (_optional_text(entry.get("city")), _optional_text(entry.get("country"))) if part
            )
            if text and text not in result:
                result.append(text)
        return result
    text = ", ".join(
        part for part in (_optional_text(raw.get("city")), _optional_text(raw.get("country"))) if part
    )
    return [text] if text else []


def _parse_date(value: Any) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
