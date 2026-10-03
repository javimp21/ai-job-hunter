"""Read and normalize public SmartRecruiters Posting API listings."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy

SMARTRECRUITERS_API_BASE = "https://api.smartrecruiters.com/v1/companies"
SMARTRECRUITERS_JOBS_BASE = "https://jobs.smartrecruiters.com"
SMARTRECRUITERS_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_SECTION_ORDER = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
_EMPLOYMENT_TYPES = {
    "full-time": EmploymentType.FULL_TIME,
    "full time": EmploymentType.FULL_TIME,
    "part-time": EmploymentType.PART_TIME,
    "part time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "internship": EmploymentType.INTERNSHIP,
    "intern": EmploymentType.INTERNSHIP,
}


class SmartRecruitersConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public SmartRecruiters company."""


class SmartRecruitersConnector:
    """Fetch public postings for a SmartRecruiters company without credentials.

    ``detail_filter`` receives each posting title; only accepted postings trigger
    the extra detail request that supplies the job-ad sections. ``None`` fetches
    the detail of every posting (still bounded by ``max_jobs``).
    """

    provider = "smartrecruiters"

    def __init__(
        self,
        company_id: str,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        page_size: int = 100,
        detail_filter: Callable[[str], bool] | None = None,
        request_delay: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        normalized = company_id.strip()
        if not normalized:
            raise ValueError("company_id must not be empty")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.company_id = normalized
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self.page_size = page_size
        self.detail_filter = detail_filter
        self.request_delay = request_delay
        self._sleep = sleep
        self._requests_made = 0
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_jobs(self) -> list[NormalizedJob]:
        base = f"{SMARTRECRUITERS_API_BASE}/{quote(self.company_id, safe='')}/postings"
        discovered_at = datetime.now(UTC)
        self._requests_made = 0
        offers: list[NormalizedJob] = []
        offset = 0
        total: int | None = None
        while (total is None or offset < total) and (
            self.max_jobs is None or len(offers) < self.max_jobs
        ):
            page_limit = self.page_size
            if self.max_jobs is not None:
                page_limit = min(page_limit, self.max_jobs - len(offers))
            payload = self._get_json(base, {"limit": page_limit, "offset": offset})
            if not isinstance(payload, dict):
                raise SmartRecruitersConnectorError("SmartRecruiters response must be a JSON object.")
            content = payload.get("content")
            found = payload.get("totalFound")
            if not isinstance(content, list) or isinstance(found, bool) or not isinstance(found, int):
                raise SmartRecruitersConnectorError(
                    "SmartRecruiters response does not match public posting fields."
                )
            total = found
            if not content:
                break
            for index, raw in enumerate(content):
                if self.max_jobs is not None and len(offers) >= self.max_jobs:
                    break
                if not isinstance(raw, dict):
                    raise SmartRecruitersConnectorError(
                        f"SmartRecruiters posting at offset {offset + index} is not a JSON object."
                    )
                try:
                    offers.append(self._build_job(base, raw, discovered_at))
                except (TypeError, ValueError) as error:
                    raise SmartRecruitersConnectorError(
                        f"SmartRecruiters posting at offset {offset + index} does not match public posting fields."
                    ) from error
            offset += len(content)
        return offers

    def _build_job(self, base: str, raw: Mapping[str, Any], discovered_at: datetime) -> NormalizedJob:
        posting_id = _identifier(raw.get("id"))
        title = _optional_text(raw.get("name"))
        if posting_id is None or title is None:
            raise ValueError("id and name are required")
        detail: Mapping[str, Any] | None = None
        if self.detail_filter is None or self.detail_filter(title):
            detail = self._get_detail(base, posting_id)
        return _normalize_job(
            raw,
            detail,
            company_id=self.company_id,
            company_name=self.company_name,
            discovered_at=discovered_at,
        )

    def _get_detail(self, base: str, posting_id: str) -> Mapping[str, Any] | None:
        try:
            payload = self._get_json(f"{base}/{quote(posting_id, safe='')}", None)
        except _NotFound:
            return None
        if not isinstance(payload, dict):
            raise SmartRecruitersConnectorError("SmartRecruiters detail must be a JSON object.")
        return payload

    def _get_json(self, url: str, params: dict[str, int] | None) -> Any:
        if self._requests_made and self.request_delay:
            self._sleep(self.request_delay)
        self._requests_made += 1
        try:
            response = self._client.get(
                url,
                params=params,
                headers={"Accept": "application/json", "User-Agent": SMARTRECRUITERS_USER_AGENT},
            )
        except httpx.RequestError as error:
            raise SmartRecruitersConnectorError(
                "Could not reach the SmartRecruiters Posting API."
            ) from error
        if params is None and response.status_code in {404, 410}:
            # A posting can be withdrawn between the list and the detail request.
            raise _NotFound
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise SmartRecruitersConnectorError(
                f"SmartRecruiters Posting API returned HTTP {error.response.status_code}."
            ) from error
        try:
            return response.json()
        except ValueError as error:
            raise SmartRecruitersConnectorError(
                "SmartRecruiters Posting API returned invalid JSON."
            ) from error

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SmartRecruitersConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class _NotFound(Exception):
    pass


def _normalize_job(
    raw: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    *,
    company_id: str,
    company_name: str | None,
    discovered_at: datetime,
) -> NormalizedJob:
    posting_id = _identifier(raw.get("id"))
    title = _optional_text(raw.get("name"))
    if posting_id is None or title is None:
        raise ValueError("id and name are required")
    location_raw = raw.get("location")
    location_raw = location_raw if isinstance(location_raw, dict) else {}
    location = _location(location_raw)
    if location is not None and len(location) > 255:
        location = None
    if location_raw.get("remote") is True:
        remote_policy: RemotePolicy | None = RemotePolicy.REMOTE
    elif location_raw.get("hybrid") is True:
        remote_policy = RemotePolicy.HYBRID
    else:
        remote_policy = None
    company = raw.get("company")
    employer = _optional_text(company.get("name")) if isinstance(company, dict) else None
    employment = raw.get("typeOfEmployment")
    employment_label = _optional_text(employment.get("label")) if isinstance(employment, dict) else None
    public_url = f"{SMARTRECRUITERS_JOBS_BASE}/{quote(company_id, safe='')}/{quote(posting_id, safe='')}"
    metadata: dict[str, Any] = dict(raw)
    if detail is not None:
        metadata["detail"] = dict(detail)
    return NormalizedJob(
        provider=SmartRecruitersConnector.provider,
        external_id=posting_id,
        source_url=public_url,
        canonical_url=public_url,
        apply_url=public_url,
        title=title,
        company_name=company_name or employer,
        description=_description(detail),
        location=location,
        remote_policy=remote_policy,
        # `remote` states the work mode, not the countries remote work is allowed from.
        employment_type=_EMPLOYMENT_TYPES.get(employment_label.casefold()) if employment_label else None,
        published_at=_parse_timestamp(raw.get("releasedDate")),
        raw_metadata=metadata,
        discovered_at=discovered_at,
    )


def _description(detail: Mapping[str, Any] | None) -> str | None:
    if detail is None:
        return None
    job_ad = detail.get("jobAd")
    sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
    if not isinstance(sections, dict):
        return None
    parts: list[str] = []
    for key in _SECTION_ORDER:
        section = sections.get(key)
        if isinstance(section, dict):
            text = html_to_text(_optional_text(section.get("text")))
            if text:
                parts.append(text)
    return "\n\n".join(parts) or None


def _location(raw: Mapping[str, Any]) -> str | None:
    full = _optional_text(raw.get("fullLocation"))
    if full:
        return full
    city = _optional_text(raw.get("city"))
    country = _optional_text(raw.get("country"))
    if country and len(country) == 2:
        country = country.upper()
    return ", ".join(part for part in (city, country) if part) or None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _identifier(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value).strip() or None
    return None


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
