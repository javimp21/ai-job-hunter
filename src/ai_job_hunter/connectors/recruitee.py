"""Read and normalize public Recruitee career sites through their keyless offers API."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy, SalaryPeriod

RECRUITEE_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_COMPANY_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})$")
_MAX_RESPONSE_BYTES = 30 * 1024 * 1024
_EMPLOYMENT_TYPES = {
    "fulltime_permanent": EmploymentType.FULL_TIME,
    "fulltime": EmploymentType.FULL_TIME,
    "parttime": EmploymentType.PART_TIME,
    "parttime_permanent": EmploymentType.PART_TIME,
    "fulltime_fixed_term": EmploymentType.CONTRACT,
    "freelance": EmploymentType.CONTRACT,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "internship": EmploymentType.INTERNSHIP,
    "trainee": EmploymentType.INTERNSHIP,
}
_SALARY_PERIODS = {
    "hour": SalaryPeriod.HOUR,
    "day": SalaryPeriod.DAY,
    "week": SalaryPeriod.WEEK,
    "month": SalaryPeriod.MONTH,
    "year": SalaryPeriod.YEAR,
}


class RecruiteeConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Recruitee career site."""


class RecruiteeConnector:
    """Fetch publicly published jobs from ``{company}.recruitee.com/api/offers/``."""

    provider = "recruitee"

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
            raise ValueError("company must be a Recruitee subdomain label")
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
    def offers_url(self) -> str:
        return f"https://{self.company}.recruitee.com/api/offers/"

    def fetch_jobs(self) -> list[NormalizedJob]:
        try:
            response = self._client.get(
                self.offers_url, headers={"Accept": "application/json", "User-Agent": RECRUITEE_USER_AGENT}
            )
        except httpx.RequestError as error:
            raise RecruiteeConnectorError("Could not reach the Recruitee offers API.") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RecruiteeConnectorError(
                f"Recruitee offers API returned HTTP {error.response.status_code}."
            ) from error
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise RecruiteeConnectorError("Recruitee offers API response is too large.")
        try:
            payload = response.json()
        except ValueError as error:
            raise RecruiteeConnectorError("Recruitee offers API returned invalid JSON.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
            raise RecruiteeConnectorError("Recruitee response must contain an offers list.")

        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, raw in enumerate(payload["offers"]):
            if self.max_jobs is not None and len(offers) >= self.max_jobs:
                break
            if not isinstance(raw, dict):
                raise RecruiteeConnectorError(f"Recruitee offer at index {index} is not a JSON object.")
            if raw.get("status") not in (None, "published"):
                continue
            try:
                offers.append(_normalize_offer(raw, company_name=self.company_name, discovered_at=discovered_at))
            except (TypeError, ValueError) as error:
                raise RecruiteeConnectorError(
                    f"Recruitee offer at index {index} does not match public offer fields."
                ) from error
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> RecruiteeConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_offer(
    raw: Mapping[str, Any], *, company_name: str | None, discovered_at: datetime
) -> NormalizedJob:
    title = _optional_text(raw.get("title"))
    url = _optional_text(raw.get("careers_url"))
    if title is None or url is None:
        raise ValueError("title and careers_url are required")
    identifier = raw.get("id")
    external_id = str(identifier) if isinstance(identifier, int) and not isinstance(identifier, bool) else url
    location = _optional_text(raw.get("location"))
    if location is not None and len(location) > 255:
        location = None
    description = "\n\n".join(
        part
        for part in (
            html_to_text(raw["description"]) if isinstance(raw.get("description"), str) else None,
            html_to_text(raw["requirements"]) if isinstance(raw.get("requirements"), str) else None,
        )
        if part
    )
    salary_min, salary_max, currency, period = _salary(raw.get("salary"))
    employment = _optional_text(raw.get("employment_type_code"))
    return NormalizedJob(
        provider=RecruiteeConnector.provider,
        external_id=external_id,
        source_url=url,
        canonical_url=url,
        apply_url=_optional_text(raw.get("careers_apply_url")) or url,
        title=title[:255],
        company_name=company_name or _optional_text(raw.get("company_name")),
        description=description or None,
        location=location,
        remote_policy=_remote_policy(raw),
        employment_type=_EMPLOYMENT_TYPES.get(employment.casefold()) if employment else None,
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_period=period,
        published_at=_parse_timestamp(raw.get("published_at") or raw.get("created_at")),
        raw_metadata={
            "department": _optional_text(raw.get("department")),
            "countryCode": _optional_text(raw.get("country_code")),
            "experience": _optional_text(raw.get("experience_code")),
            "employmentType": employment,
            "remote": raw.get("remote") if isinstance(raw.get("remote"), bool) else None,
            "hybrid": raw.get("hybrid") if isinstance(raw.get("hybrid"), bool) else None,
        },
        discovered_at=discovered_at,
    )


def _remote_policy(raw: Mapping[str, Any]) -> RemotePolicy | None:
    # Recruitee states each mode as a boolean; a False flag is "not stated", never "on-site".
    if raw.get("remote") is True:
        return RemotePolicy.REMOTE
    if raw.get("hybrid") is True:
        return RemotePolicy.HYBRID
    if raw.get("on_site") is True:
        return RemotePolicy.ONSITE
    return None


def _salary(value: Any) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None]:
    if not isinstance(value, Mapping):
        return None, None, None, None
    currency = _optional_text(value.get("currency"))
    period = _SALARY_PERIODS.get((_optional_text(value.get("period")) or "").casefold())
    low, high = _amount(value.get("min")), _amount(value.get("max"))
    if currency is None or not re.fullmatch(r"[A-Za-z]{3}", currency) or period is None or (low is None and high is None):
        return None, None, None, None
    return low, high, currency.upper(), period


def _amount(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _parse_timestamp(value: Any) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" UTC", "+00:00").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
