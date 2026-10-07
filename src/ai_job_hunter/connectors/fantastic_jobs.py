"""Fantastic.jobs job-board feed (https://fantastic.jobs): recent postings from LinkedIn and other boards.

``GET https://data.fantastic.jobs/v1/active-jb`` returns, for a time window (``time_frame`` 1h, 24h, 7d or 6m) and
Google-style ``title`` / ``location`` filters, the postings found in that window, with the full description when
``description_format=text`` is sent. One job returned costs one job credit and every request costs one request credit
(the trial gives 500 jobs and 50 requests a week), so the connector asks for one page of at most ``page_size`` jobs per
poll and keeps a daily job budget in ``data/local/fantastic-jobs-credits.json``. The remaining credits the API reports
in its response headers are respected as well. The key (``FANTASTIC_JOBS_API_KEY``) only travels in the Authorization
header and never appears in errors.

The vendor's own classifications (``ai_*`` fields: experience level, work arrangement, salary) are model guesses, not
facts from the employer: they are kept in ``raw_metadata`` and never used to evaluate; the work mode and salary are
left unknown unless the posting text states them (see ``services/text_facts``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from ai_job_hunter.connectors._portal_http import new_client
from ai_job_hunter.connectors.theirstack import CreditBudget
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob

ACTIVE_JOBS_URL = "https://data.fantastic.jobs/v1/active-jb"
DEFAULT_COUNTRIES = ("Spain", "Netherlands", "Switzerland", "Ireland", "Luxembourg", "Germany", "Belgium")
DEFAULT_TITLES = (
    "backend engineer", "backend developer", "software engineer", "software developer", "java developer",
    "python developer", "platform engineer", "ai engineer", "forward deployed engineer",
)
# Title words that are never wanted: excluding them in the request saves job credits.
DEFAULT_EXCLUDED_TITLE_WORDS = ("senior", "staff", "principal", "lead", "head", "manager", "director", "architect")
DEFAULT_CREDITS_PATH = Path("data/local/fantastic-jobs-credits.json")
MAX_PAGE_SIZE = 100


class FantasticJobsConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only; never the key)."""


class FantasticJobsNotConfigured(FantasticJobsConnectorError):
    """FANTASTIC_JOBS_API_KEY is not set; the portal is skipped."""


def build_query(
    *,
    titles: Sequence[str] = DEFAULT_TITLES,
    countries: Sequence[str] = DEFAULT_COUNTRIES,
    excluded: Sequence[str] = DEFAULT_EXCLUDED_TITLE_WORDS,
    time_frame: str = "24h",
    limit: int = MAX_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    # ``title_advanced`` (Boolean: | OR, & AND, ! NOT, single-quoted phrases). The Google-style ``title`` parameter does
    # not bind "-senior" to a list of OR terms: half of the postings returned on 2026-10-07 were senior roles.
    include = "(" + " | ".join(f"'{title}'" for title in titles) + ")"
    exclude = "".join(f" & !{word}" for word in excluded)
    return {
        "time_frame": time_frame,
        "title_advanced": f"{include}{exclude}",
        "location": " OR ".join(f'"{country}"' for country in countries),
        "description_format": "text",
        "limit": limit,
        "offset": offset,
    }


class FantasticJobsConnector:
    provider = "fantastic_jobs"

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        budget: CreditBudget | None = None,
        page_size: int = MAX_PAGE_SIZE,
        time_frame: str = "24h",
        titles: Sequence[str] = DEFAULT_TITLES,
        countries: Sequence[str] = DEFAULT_COUNTRIES,
        excluded: Sequence[str] = DEFAULT_EXCLUDED_TITLE_WORDS,
        client: httpx.Client | None = None,
        timeout: float = 40.0,
    ) -> None:
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        self._key = _secret(api_key)
        self._budget = budget or CreditBudget(DEFAULT_CREDITS_PATH, 70)
        self._page_size = page_size
        self._time_frame = time_frame
        self._titles, self._countries, self._excluded = tuple(titles), tuple(countries), tuple(excluded)
        self._client = client
        self._timeout = timeout
        self.last_headers: dict[str, str] = {}  # the x-api-* balances of the last response (no secrets)

    @classmethod
    def from_settings(cls, client: httpx.Client | None = None) -> FantasticJobsConnector:
        from ai_job_hunter.config import get_settings

        settings = get_settings()

        def csv(value: str, default: Sequence[str]) -> tuple[str, ...]:
            items = tuple(part.strip() for part in value.split(",") if part.strip())
            return items or tuple(default)

        return cls(
            api_key=settings.fantastic_jobs_api_key,
            budget=CreditBudget(DEFAULT_CREDITS_PATH, settings.fantastic_jobs_daily_credits),
            time_frame=settings.fantastic_jobs_time_frame,
            titles=csv(settings.fantastic_jobs_titles, DEFAULT_TITLES),
            countries=csv(settings.fantastic_jobs_countries, DEFAULT_COUNTRIES),
            client=client,
        )

    def fetch_jobs(self) -> list[NormalizedJob]:
        if not self._key:
            raise FantasticJobsNotConfigured(
                "Fantastic.jobs skipped: set FANTASTIC_JOBS_API_KEY in .env to enable it."
            )
        limit = min(self._page_size, self._budget.remaining())
        if limit <= 0:
            return []  # today's job budget is spent
        payload = self._get(
            build_query(
                titles=self._titles, countries=self._countries, excluded=self._excluded,
                time_frame=self._time_frame, limit=limit,
            )
        )
        jobs = payload.get("data") if isinstance(payload, Mapping) else payload
        if not isinstance(jobs, list):
            raise FantasticJobsConnectorError("Fantastic.jobs returned an unexpected payload.")
        remaining = _int(self.last_headers.get("x-api-jobs-remaining"))
        discovered_at = datetime.now(UTC)
        offers: dict[str, NormalizedJob] = {}
        for raw in jobs:
            if not isinstance(raw, Mapping):
                continue
            try:
                offer = _normalize_job(raw, discovered_at=discovered_at)
            except ValueError:
                continue
            offers.setdefault(offer.external_id or offer.source_url or offer.title, offer)
        self._budget.spend(len(jobs))  # one credit per job returned, valid or not
        if remaining is not None and remaining <= 0:
            self._budget.spend(self._budget.remaining())  # the account is empty: nothing more today
        return list(offers.values())

    def _get(self, params: dict[str, Any]) -> Any:
        client = self._client or new_client(self._timeout)
        try:
            try:
                response = client.get(
                    ACTIVE_JOBS_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
                    timeout=self._timeout,
                )
            except httpx.HTTPError as error:
                raise FantasticJobsConnectorError(
                    f"Fantastic.jobs request failed ({type(error).__name__})."
                ) from None
            self.last_headers = {
                key.lower(): value for key, value in response.headers.items() if key.lower().startswith("x-api-")
            }
            if response.status_code != 200:
                raise FantasticJobsConnectorError(f"Fantastic.jobs returned HTTP {response.status_code}.")
            try:
                return response.json()
            except ValueError:
                raise FantasticJobsConnectorError("Fantastic.jobs returned invalid JSON.") from None
        finally:
            if self._client is None:
                client.close()


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("title"))
    url = _https(raw.get("url"))
    if title is None or url is None:
        raise ValueError("title and a posting URL are required")
    raw_id = raw.get("id")
    external_id = str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None
    locations = [text for text in (raw.get("locations_derived") or []) if isinstance(text, str) and text.strip()]
    location = "; ".join(locations)[:255] or None
    employment = raw.get("ai_employment_type")
    return NormalizedJob(
        provider=FantasticJobsConnector.provider,
        external_id=f"fantastic:{external_id}" if external_id else None,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title[:255],
        company_name=(_text(raw.get("organization")) or "")[:255] or None,
        description=_text(raw.get("description_text")),
        location=location,
        employment_type=_employment_type(employment),
        published_at=_published(raw.get("date_posted")),
        discovered_at=discovered_at,
        raw_metadata={
            "board": _text(raw.get("source")),
            "countries": [c for c in (raw.get("countries_derived") or []) if isinstance(c, str)][:5] or None,
            # The vendor's own model guesses: hints for a human, never evaluated.
            "aiExperienceLevel": _text(raw.get("ai_experience_level")),
            "aiWorkArrangement": _text(raw.get("ai_work_arrangement")),
            "aiJobLanguage": _text(raw.get("ai_job_language")),
        },
    )


def _employment_type(value: Any) -> EmploymentType | None:
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    kinds = {item.casefold().replace("-", "_").replace(" ", "_") for item in items if isinstance(item, str)}
    if "full_time" in kinds or "fulltime" in kinds:
        return EmploymentType.FULL_TIME
    if "part_time" in kinds or "parttime" in kinds:
        return EmploymentType.PART_TIME
    return None


def _published(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _https(value: Any) -> str | None:
    text = _text(value)
    if text is None or len(text) > 2048:
        return None
    parts = urlsplit(text)
    return text if parts.scheme == "https" and parts.hostname else None


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _secret(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    return (value.get_secret_value() if isinstance(value, SecretStr) else value).strip()
