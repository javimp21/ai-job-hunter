"""Adzuna job-search API for Spain (needs a free app id/key).

Adzuna lists on-site and remote jobs from many employers. The free tier allows
roughly 250 calls a day, so the connector runs a handful of searches with at
most two pages each. Adzuna's terms ask for a visible "Jobs by Adzuna" credit
and link; alerts add it. Adzuna's `description` is only a truncated snippet and
its salary is frequently an estimate (`salary_is_predicted`), which is never
kept as a published salary. The API carries no work-mode or remote-eligibility
field, so both stay unknown.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from ai_job_hunter.connectors._portal_http import get_json, new_client
from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, SalaryPeriod

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/es/search/{page}"
# (what, where): on-site roles in Madrid, then the same roles with "remoto" nationwide.
DEFAULT_SEARCHES: tuple[tuple[str, str | None], ...] = (
    ("backend engineer", "Madrid"),
    ("java developer", "Madrid"),
    ("python developer", "Madrid"),
    ("AI engineer", "Madrid"),
    ("backend engineer remoto", None),
    ("java developer remoto", None),
    ("python developer remoto", None),
    ("AI engineer remoto", None),
)
_PAGE_SIZE = 50
_ADZUNA_HOSTS = {"adzuna.es", "adzuna.com"}


class AdzunaConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only; never credentials)."""


class AdzunaNotConfigured(AdzunaConnectorError):
    """ADZUNA_APP_ID / ADZUNA_APP_KEY are not set; the portal is skipped."""


class AdzunaConnector:
    provider = "adzuna"

    def __init__(
        self,
        *,
        app_id: SecretStr | str | None,
        app_key: SecretStr | str | None,
        searches: Sequence[tuple[str, str | None]] = DEFAULT_SEARCHES,
        max_pages: int = 2,
        max_days_old: int = 7,
        pause_seconds: float = 1.0,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        if not searches:
            raise ValueError("at least one search is required")
        self._app_id = _secret(app_id)
        self._app_key = _secret(app_key)
        self.searches = tuple(searches)
        self.max_pages = max_pages
        self.max_days_old = max_days_old
        self._pause = pause_seconds
        self._client = client
        self._timeout = timeout

    @classmethod
    def from_settings(cls, client: httpx.Client | None = None) -> AdzunaConnector:
        from ai_job_hunter.config import get_settings

        settings = get_settings()
        return cls(app_id=settings.adzuna_app_id, app_key=settings.adzuna_app_key, client=client)

    def fetch_jobs(self) -> list[NormalizedJob]:
        if not self._app_id or not self._app_key:
            raise AdzunaNotConfigured("Adzuna skipped: set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env to enable it.")
        client = self._client or new_client(self._timeout)
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        first = True
        try:
            for what, where in self.searches:
                for page in range(1, self.max_pages + 1):
                    if not first and self._pause:
                        time.sleep(self._pause)
                    first = False
                    params: dict[str, Any] = {
                        "app_id": self._app_id,
                        "app_key": self._app_key,
                        "results_per_page": _PAGE_SIZE,
                        "what": what,
                        "max_days_old": self.max_days_old,
                        "sort_by": "date",
                    }
                    if where:
                        params["where"] = where
                    payload = get_json(
                        client,
                        SEARCH_URL.format(page=page),
                        params,
                        portal="Adzuna",
                        error=AdzunaConnectorError,
                        timeout=self._timeout,
                    )
                    if not isinstance(payload, Mapping):
                        raise AdzunaConnectorError("Adzuna returned an unexpected payload.")
                    results = [item for item in payload.get("results") or [] if isinstance(item, Mapping)]
                    for raw in results:
                        try:
                            job = _normalize_job(raw, discovered_at=discovered_at)
                        except ValueError:
                            continue
                        jobs.setdefault(job.external_id or job.source_url or job.title, job)
                    if len(results) < _PAGE_SIZE:
                        break
        finally:
            if self._client is None:
                client.close()
        return list(jobs.values())


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("title"))
    url = _text(raw.get("redirect_url"))
    if title is None or url is None:
        raise ValueError("title and redirect_url are required")
    host = (urlsplit(url).hostname or "").lower()
    if urlsplit(url).scheme != "https" or not any(host == h or host.endswith("." + h) for h in _ADZUNA_HOSTS):
        raise ValueError("redirect_url must be an Adzuna URL")
    raw_id = raw.get("id")
    external_id = str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None
    company = raw.get("company")
    location = raw.get("location")
    predicted = str(raw.get("salary_is_predicted", "")).strip().casefold() in {"1", "true"}
    salary_min = None if predicted else _decimal(raw.get("salary_min"))
    salary_max = None if predicted else _decimal(raw.get("salary_max"))
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        salary_min = salary_max = None
    has_salary = salary_min is not None or salary_max is not None
    return NormalizedJob(
        provider=AdzunaConnector.provider,
        external_id=external_id or None,
        source_url=url,
        canonical_url=None,
        apply_url=url,
        title=title,
        company_name=_text(company.get("display_name")) if isinstance(company, Mapping) else None,
        description=html_to_text(_text(raw.get("description"))),
        location=(_text(location.get("display_name")) if isinstance(location, Mapping) else None),
        salary_min=salary_min,
        salary_max=salary_max,
        # Adzuna Spain quotes annual EUR salaries.
        currency="EUR" if has_salary else None,
        salary_period=SalaryPeriod.YEAR if has_salary else None,
        employment_type=_employment_type(raw),
        published_at=_timestamp(raw.get("created")),
        discovered_at=discovered_at,
        raw_metadata={key: value for key, value in raw.items() if key != "description"},
    )


def _employment_type(raw: Mapping[str, Any]) -> EmploymentType | None:
    if str(raw.get("contract_type") or "").casefold() == "contract":
        return EmploymentType.CONTRACT
    return {"full_time": EmploymentType.FULL_TIME, "part_time": EmploymentType.PART_TIME}.get(
        str(raw.get("contract_time") or "").casefold()
    )


def _secret(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    return (value.get_secret_value() if isinstance(value, SecretStr) else value).strip()


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number > 0 else None


def _timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
