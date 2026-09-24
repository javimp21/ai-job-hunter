"""Read and normalize public Greenhouse Job Board API listings."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import NormalizedJob

GREENHOUSE_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
GREENHOUSE_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"


class GreenhouseConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Greenhouse job board."""


class GreenhouseConnector:
    """Fetch one company's publicly published Greenhouse job board."""

    provider = "greenhouse"

    def __init__(
        self,
        board_token: str,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        token = board_token.strip()
        if not token:
            raise ValueError("board_token must not be empty")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.board_token = token
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": GREENHOUSE_USER_AGENT},
        )

    def fetch_jobs(self) -> list[NormalizedJob]:
        """Fetch all listed job posts with descriptions in one public GET."""

        url = f"{GREENHOUSE_API_BASE}/{quote(self.board_token, safe='')}/jobs"
        try:
            response = self._client.get(
                url,
                params={"content": "true"},
                headers={"Accept": "application/json", "User-Agent": GREENHOUSE_USER_AGENT},
            )
        except httpx.RequestError as error:
            raise GreenhouseConnectorError("Could not reach the Greenhouse Job Board API.") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GreenhouseConnectorError(
                f"Greenhouse Job Board API returned HTTP {error.response.status_code}."
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise GreenhouseConnectorError("Greenhouse Job Board API returned invalid JSON.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise GreenhouseConnectorError("Greenhouse response must contain a jobs list.")

        raw_jobs = payload["jobs"]
        selected = raw_jobs if self.max_jobs is None else raw_jobs[: self.max_jobs]
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, raw_job in enumerate(selected):
            if not isinstance(raw_job, dict):
                raise GreenhouseConnectorError(
                    f"Greenhouse job at index {index} is not a JSON object."
                )
            try:
                offers.append(
                    _normalize_job(
                        raw_job,
                        company_name=self.company_name,
                        discovered_at=discovered_at,
                    )
                )
            except (TypeError, ValueError) as error:
                raise GreenhouseConnectorError(
                    f"Greenhouse job at index {index} does not match the public board fields."
                ) from error
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GreenhouseConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_job(
    raw: Mapping[str, Any], *, company_name: str | None, discovered_at: datetime
) -> NormalizedJob:
    title = _required_text(raw, "title")
    absolute_url = _optional_text(raw.get("absolute_url"))
    location_data = raw.get("location")
    location = _optional_text(location_data.get("name")) if isinstance(location_data, dict) else None
    if location is not None and len(location) > 255:
        # Keep the full source value in raw_metadata rather than truncating a list
        # of permitted work locations into a misleading geography label.
        location = None
    published_at = _parse_timestamp(raw.get("first_published"))
    return NormalizedJob(
        provider=GreenhouseConnector.provider,
        external_id=_identifier(raw.get("id")),
        source_url=absolute_url,
        canonical_url=absolute_url,
        # The public board API exposes one hosted job URL, not a separate apply URL.
        apply_url=None,
        title=title,
        company_name=_optional_text(raw.get("company_name")) or company_name,
        description=html_to_text(_optional_text(raw.get("content"))),
        location=location,
        published_at=published_at,
        raw_metadata=dict(raw),
        discovered_at=discovered_at,
    )


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = _optional_text(record.get(field))
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _identifier(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value).strip() or None
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
