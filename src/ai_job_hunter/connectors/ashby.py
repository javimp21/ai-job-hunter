"""Read current public Ashby job postings through the documented posting API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy, SalaryPeriod

ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"
ASHBY_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_EMPLOYMENT_TYPES = {
    "fulltime": EmploymentType.FULL_TIME,
    "parttime": EmploymentType.PART_TIME,
    "intern": EmploymentType.INTERNSHIP,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
}
_INTERVALS = {
    "hour": SalaryPeriod.HOUR,
    "1 hour": SalaryPeriod.HOUR,
    "day": SalaryPeriod.DAY,
    "1 day": SalaryPeriod.DAY,
    "week": SalaryPeriod.WEEK,
    "1 week": SalaryPeriod.WEEK,
    "month": SalaryPeriod.MONTH,
    "1 month": SalaryPeriod.MONTH,
    "year": SalaryPeriod.YEAR,
    "1 year": SalaryPeriod.YEAR,
}


class AshbyConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Ashby job board."""


class AshbyConnector:
    """Fetch listed, currently published Ashby postings for one job board."""

    provider = "ashby"

    def __init__(
        self,
        job_board_name: str,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        board_name = job_board_name.strip()
        if not board_name:
            raise ValueError("job_board_name must not be empty")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.job_board_name = board_name
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": ASHBY_USER_AGENT},
        )

    def fetch_jobs(self) -> list[NormalizedJob]:
        url = f"{ASHBY_API_BASE}/{quote(self.job_board_name, safe='')}"
        try:
            response = self._client.get(
                url,
                params={"includeCompensation": "true"},
                headers={"Accept": "application/json", "User-Agent": ASHBY_USER_AGENT},
            )
        except httpx.RequestError as error:
            raise AshbyConnectorError("Could not reach the Ashby Job Posting API.") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise AshbyConnectorError(
                f"Ashby Job Posting API returned HTTP {error.response.status_code}."
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise AshbyConnectorError("Ashby Job Posting API returned invalid JSON.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise AshbyConnectorError("Ashby response must contain a jobs list.")

        # Ashby can include published but unlisted direct-link postings. Keep only
        # entries the company marks as listed on its public job board.
        listed_jobs = [job for job in payload["jobs"] if not isinstance(job, dict) or job.get("isListed") is not False]
        selected = listed_jobs if self.max_jobs is None else listed_jobs[: self.max_jobs]
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for index, raw_job in enumerate(selected):
            if not isinstance(raw_job, dict):
                raise AshbyConnectorError(f"Ashby job at index {index} is not a JSON object.")
            try:
                offers.append(
                    _normalize_job(
                        raw_job,
                        company_name=self.company_name,
                        discovered_at=discovered_at,
                    )
                )
            except (TypeError, ValueError) as error:
                raise AshbyConnectorError(
                    f"Ashby job at index {index} does not match public posting fields."
                ) from error
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> AshbyConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_job(
    raw: Mapping[str, Any], *, company_name: str | None, discovered_at: datetime
) -> NormalizedJob:
    title = _required_text(raw, "title")
    hosted_url = _optional_text(raw.get("jobUrl"))
    apply_url = _optional_text(raw.get("applyUrl"))
    remote_policy = _remote_policy(raw.get("workplaceType"))
    if remote_policy is None and raw.get("isRemote") is True:
        remote_policy = RemotePolicy.REMOTE
    salary_min, salary_max, currency, salary_period = _salary(raw.get("compensation"))
    description = _optional_text(raw.get("descriptionPlain"))
    if description is None:
        description = html_to_text(_optional_text(raw.get("descriptionHtml")))
    location = _location(raw)
    if location is not None and len(location) > 255:
        # The entire multi-location payload remains available in raw_metadata.
        location = None
    return NormalizedJob(
        provider=AshbyConnector.provider,
        external_id=_identifier(raw.get("id")),
        source_url=hosted_url or apply_url,
        canonical_url=hosted_url,
        apply_url=apply_url,
        title=title,
        company_name=_optional_text(raw.get("companyName")) or company_name,
        description=description,
        location=location,
        remote_policy=remote_policy,
        # A remote workplace mode does not establish eligible countries.
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_period=salary_period,
        employment_type=_employment_type(raw.get("employmentType")),
        published_at=_parse_timestamp(raw.get("publishedAt")),
        raw_metadata=dict(raw),
        discovered_at=discovered_at,
    )


def _location(raw: Mapping[str, Any]) -> str | None:
    values: list[str] = []
    primary = _optional_text(raw.get("location"))
    if primary:
        values.append(primary)
    secondary = raw.get("secondaryLocations")
    if isinstance(secondary, list):
        for entry in secondary:
            if not isinstance(entry, dict):
                continue
            location = _optional_text(entry.get("location"))
            if location:
                values.append(location)
    address = raw.get("address")
    postal = address.get("postalAddress") if isinstance(address, dict) else None
    if not values and isinstance(postal, dict):
        values.extend(
            value
            for value in (
                _optional_text(postal.get("addressLocality")),
                _optional_text(postal.get("addressRegion")),
                _optional_text(postal.get("addressCountry")),
            )
            if value
        )
    return "; ".join(dict.fromkeys(values)) or None


def _salary(value: Any) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None]:
    if not isinstance(value, dict):
        return None, None, None, None
    components = value.get("summaryComponents")
    if not isinstance(components, list):
        tiers = value.get("compensationTiers")
        if not isinstance(tiers, list) or len(tiers) != 1 or not isinstance(tiers[0], dict):
            return None, None, None, None
        components = tiers[0].get("components")
    if not isinstance(components, list):
        return None, None, None, None
    salary_components = [
        component
        for component in components
        if isinstance(component, dict)
        and _optional_text(component.get("compensationType")) == "Salary"
    ]
    if len(salary_components) != 1:
        return None, None, None, None
    salary = salary_components[0]
    currency = _optional_text(salary.get("currencyCode"))
    currency = currency.upper() if currency and len(currency) == 3 and currency.isalpha() else None
    interval = _optional_text(salary.get("interval"))
    period = _INTERVALS.get(interval.casefold()) if interval else None
    minimum = _decimal(salary.get("minValue"))
    maximum = _decimal(salary.get("maxValue"))
    if (
        currency is None
        or period is None
        or (minimum is None and maximum is None)
        or (minimum is not None and maximum is not None and minimum > maximum)
    ):
        return None, None, None, None
    return minimum, maximum, currency, period


def _employment_type(value: Any) -> EmploymentType | None:
    text = _optional_text(value)
    if text is None:
        return None
    return _EMPLOYMENT_TYPES.get("".join(char for char in text.casefold() if char.isalnum()))


def _remote_policy(value: Any) -> RemotePolicy | None:
    text = _optional_text(value)
    if text is None:
        return None
    return {
        "onsite": RemotePolicy.ONSITE,
        "remote": RemotePolicy.REMOTE,
        "hybrid": RemotePolicy.HYBRID,
    }.get(text.casefold())


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def _identifier(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value).strip() or None
    return None


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = _optional_text(record.get(field))
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None
