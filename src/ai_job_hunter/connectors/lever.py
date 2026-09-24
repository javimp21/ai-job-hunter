"""Read and normalize public Lever Postings API listings."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemotePolicy,
    SalaryPeriod,
)

LEVER_API_BASES = {
    "global": "https://api.lever.co/v0/postings",
    "eu": "https://api.eu.lever.co/v0/postings",
}
LEVER_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_EMPLOYMENT_TYPES = {
    "full time": EmploymentType.FULL_TIME,
    "fulltime": EmploymentType.FULL_TIME,
    "part time": EmploymentType.PART_TIME,
    "parttime": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "intern": EmploymentType.INTERNSHIP,
    "internship": EmploymentType.INTERNSHIP,
}
_SALARY_PERIODS = {
    "hour": SalaryPeriod.HOUR,
    "hourly": SalaryPeriod.HOUR,
    "day": SalaryPeriod.DAY,
    "daily": SalaryPeriod.DAY,
    "week": SalaryPeriod.WEEK,
    "weekly": SalaryPeriod.WEEK,
    "month": SalaryPeriod.MONTH,
    "monthly": SalaryPeriod.MONTH,
    "year": SalaryPeriod.YEAR,
    "yearly": SalaryPeriod.YEAR,
    "annual": SalaryPeriod.YEAR,
}


class LeverConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Lever postings site."""


class LeverConnector:
    """Fetch publicly published posts for a Lever site without credentials."""

    provider = "lever"
    page_size = 100

    def __init__(
        self,
        site: str,
        *,
        company_name: str | None = None,
        region: str = "global",
        max_jobs: int | None = None,
        page_size: int = 100,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        normalized_site = site.strip()
        if not normalized_site:
            raise ValueError("site must not be empty")
        if region not in LEVER_API_BASES:
            raise ValueError("region must be 'global' or 'eu'")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.site = normalized_site
        self.company_name = _optional_text(company_name)
        self.region = region
        self.max_jobs = max_jobs
        self.page_size = page_size
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": LEVER_USER_AGENT},
        )

    def fetch_jobs(self) -> list[NormalizedJob]:
        """Read published postings, using documented skip/limit pagination."""

        url = f"{LEVER_API_BASES[self.region]}/{quote(self.site, safe='')}"
        page_limit = min(self.max_jobs or self.page_size, self.page_size)
        offers: list[NormalizedJob] = []
        skip = 0
        discovered_at = datetime.now(UTC)
        while self.max_jobs is None or len(offers) < self.max_jobs:
            params = {"mode": "json", "skip": skip, "limit": page_limit}
            try:
                response = self._client.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": LEVER_USER_AGENT},
                )
            except httpx.RequestError as error:
                raise LeverConnectorError("Could not reach the Lever Postings API.") from error
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise LeverConnectorError(
                    f"Lever Postings API returned HTTP {error.response.status_code}."
                ) from error
            try:
                payload = response.json()
            except ValueError as error:
                raise LeverConnectorError("Lever Postings API returned invalid JSON.") from error
            if not isinstance(payload, list):
                raise LeverConnectorError("Lever response must be a JSON list of postings.")

            remaining = None if self.max_jobs is None else self.max_jobs - len(offers)
            page = payload if remaining is None else payload[:remaining]
            for index, raw_job in enumerate(page):
                if not isinstance(raw_job, dict):
                    raise LeverConnectorError(
                        f"Lever posting at offset {skip + index} is not a JSON object."
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
                    raise LeverConnectorError(
                        f"Lever posting at offset {skip + index} does not match public posting fields."
                    ) from error

            if len(payload) < page_limit or not payload or (
                self.max_jobs is not None and len(offers) >= self.max_jobs
            ):
                break
            skip += len(payload)
        return offers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> LeverConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_job(
    raw: Mapping[str, Any], *, company_name: str | None, discovered_at: datetime
) -> NormalizedJob:
    title = _optional_text(raw.get("text"))
    if title is None:
        raise ValueError("text is required")
    categories = raw.get("categories")
    categories = categories if isinstance(categories, dict) else {}
    location = _location(categories, raw.get("country"))
    if location is not None and len(location) > 255:
        # Preserve the complete list in raw_metadata; don't turn a partial list
        # of eligible locations into a false geographic claim.
        location = None
    workplace = _optional_text(raw.get("workplaceType"))
    remote_policy = _remote_policy(workplace)
    salary = raw.get("salaryRange")
    salary_min, salary_max, currency, salary_period = _salary(salary)
    hosted_url = _optional_text(raw.get("hostedUrl"))
    apply_url = _optional_text(raw.get("applyUrl"))
    description = _optional_text(raw.get("descriptionPlain"))
    if description is None:
        description = html_to_text(_optional_text(raw.get("description")))
    return NormalizedJob(
        provider=LeverConnector.provider,
        external_id=_identifier(raw.get("id")),
        source_url=hosted_url or apply_url,
        canonical_url=hosted_url,
        apply_url=apply_url,
        title=title,
        company_name=company_name or _optional_text(raw.get("employer")),
        description=description,
        location=location,
        remote_policy=remote_policy,
        # workplaceType states mode, not the countries from which remote work is allowed.
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_period=salary_period,
        employment_type=_employment_type(categories.get("commitment")),
        published_at=_parse_timestamp(raw.get("createdAt")),
        raw_metadata=dict(raw),
        discovered_at=discovered_at,
    )


def _location(categories: Mapping[str, Any], country: Any) -> str | None:
    primary = _optional_text(categories.get("location"))
    if primary is None:
        locations = categories.get("allLocations")
        if isinstance(locations, list):
            normalized = [_optional_text(item) for item in locations]
            primary = "; ".join(item for item in normalized if item) or None
    country_text = _optional_text(country)
    if primary and country_text and len(country_text) == 2 and country_text.casefold() not in primary.casefold():
        return f"{primary}, {country_text.upper()}"
    return primary or country_text


def _employment_type(value: Any) -> EmploymentType | None:
    text = _optional_text(value)
    if text is None:
        return None
    return _EMPLOYMENT_TYPES.get(" ".join(text.casefold().replace("-", " ").replace("_", " ").split()))


def _remote_policy(value: Any) -> RemotePolicy | None:
    text = _optional_text(value)
    if text is None:
        return None
    return {
        "onsite": RemotePolicy.ONSITE,
        "on-site": RemotePolicy.ONSITE,
        "remote": RemotePolicy.REMOTE,
        "hybrid": RemotePolicy.HYBRID,
    }.get(text.casefold())


def _salary(value: Any) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None]:
    if not isinstance(value, dict):
        return None, None, None, None
    low = _decimal(value.get("min"))
    high = _decimal(value.get("max"))
    raw_currency = _optional_text(value.get("currency"))
    currency = raw_currency.upper() if raw_currency and len(raw_currency) == 3 and raw_currency.isalpha() else None
    interval = _optional_text(value.get("interval"))
    period: SalaryPeriod | None = None
    if interval:
        normalized = interval.casefold().replace("-salary", "").replace("_salary", "")
        for token, mapped in _SALARY_PERIODS.items():
            if normalized == token or normalized == f"per-{token}" or normalized == f"per {token}":
                period = mapped
                break
    return low, high, currency, period


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _identifier(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value).strip() or None
    return None


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
