"""TheirStack job-search API (https://theirstack.com): an aggregator of postings from
career sites, ATSs and job boards, including those whose own feeds we cannot read.

Credits: TheirStack charges one credit per job returned. The connector therefore keeps a
daily credit budget (``THEIRSTACK_DAILY_CREDITS``, state in ``data/local/theirstack-credits.json``)
and never requests more jobs than the budget has left; a request that finds nothing costs
nothing. Filters are narrow on purpose: the candidate's countries, recent postings and
junior/mid seniority. The API key (``THEIRSTACK_API_KEY``) is a secret: it only travels in the
``Authorization`` header and never appears in errors or logs.

``final_url`` is the employer's own posting when TheirStack knows it; it becomes the apply link,
so alerts lead to the free employer page and the usual URL dedup merges it with the job already
read from the company's ATS. Seniority, remote flags and salary estimates from the aggregator are
not trusted as facts: seniority only narrows the request, the salary is not stored, remote
eligibility stays unknown, and the existing prefilter decides.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._portal_http import new_client, post_json
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy

SEARCH_URL = "https://api.theirstack.com/v1/jobs/search"
DEFAULT_COUNTRIES = ("ES", "NL", "CH", "IE", "LU")
DEFAULT_TITLES = (
    "backend engineer", "back-end engineer", "backend developer", "java developer", "software engineer",
    "python developer", "platform engineer", "ai engineer", "forward deployed engineer",
)
DEFAULT_SENIORITY = ("junior", "mid_level")
DEFAULT_CREDITS_PATH = Path("data/local/theirstack-credits.json")
MAX_PAGE_SIZE = 25  # the free plan rejects larger pages (HTTP 403, E-020)


class TheirStackConnectorError(RuntimeError):
    """A safe, user-readable portal failure (status or type only; never the key)."""


class TheirStackNotConfigured(TheirStackConnectorError):
    """THEIRSTACK_API_KEY is not set; the portal is skipped."""


class CreditBudget:
    """Credits spent today (UTC), persisted so every run of the day shares one budget."""

    def __init__(self, path: Path, daily: int, *, today: Callable[[], date] = lambda: datetime.now(UTC).date()) -> None:
        self._path = path
        self.daily = daily
        self._today = today

    def used(self) -> int:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(data, dict) or data.get("date") != self._today().isoformat():
            return 0
        value = data.get("used")
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0

    def remaining(self) -> int:
        return max(0, self.daily - self.used())

    def spend(self, credits: int) -> None:
        if credits <= 0:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"date": self._today().isoformat(), "used": self.used() + credits}), encoding="utf-8"
            )
        except OSError:
            pass  # a lost counter can only make the next run spend within its own page limit


def build_search_body(
    *,
    limit: int,
    countries: Sequence[str] = DEFAULT_COUNTRIES,
    titles: Sequence[str] = DEFAULT_TITLES,
    seniority: Sequence[str] = DEFAULT_SENIORITY,
    max_age_days: int = 1,
    page: int = 0,
    preview: bool = False,
    include_total: bool = False,
    companies: Sequence[str] = (),
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "posted_at_max_age_days": max_age_days,
        "job_title_or": list(titles),
        "order_by": [{"desc": True, "field": "date_posted"}],
        "limit": limit,
        "page": page,
    }
    if companies:
        # Watched employers: any country and seniority; the prefilter decides.
        body["company_name_case_insensitive_or"] = list(companies)
    else:
        body["job_country_code_or"] = list(countries)
        body["job_seniority_or"] = list(seniority)
    if preview:
        body["blur_company_data"] = True  # no credits are consumed in preview mode
    if include_total:
        body["include_total_results"] = True
    return body


class TheirStackConnector:
    provider = "theirstack"

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        budget: CreditBudget | None = None,
        page_size: int = MAX_PAGE_SIZE,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        watch_companies: Sequence[str] = (),
        countries: Sequence[str] = DEFAULT_COUNTRIES,
        titles: Sequence[str] = DEFAULT_TITLES,
        seniority: Sequence[str] = DEFAULT_SENIORITY,
    ) -> None:
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        self._key = _secret(api_key)
        self._budget = budget or CreditBudget(DEFAULT_CREDITS_PATH, 100)
        self._page_size = page_size
        self._watch = tuple(name.strip() for name in watch_companies if name.strip())
        self._countries, self._titles, self._seniority = tuple(countries), tuple(titles), tuple(seniority)
        self.page = 0  # only the measurement probe moves it, to read a page it has not paid for yet
        self._client = client
        self._timeout = timeout

    @classmethod
    def from_settings(cls, client: httpx.Client | None = None) -> TheirStackConnector:
        from ai_job_hunter.config import get_settings

        settings = get_settings()
        return cls(
            api_key=settings.theirstack_api_key,
            budget=CreditBudget(DEFAULT_CREDITS_PATH, settings.theirstack_daily_credits),
            client=client,
            watch_companies=settings.theirstack_watch_companies.split(","),
            countries=_csv(settings.theirstack_countries, DEFAULT_COUNTRIES),
            titles=_csv(settings.theirstack_titles, DEFAULT_TITLES),
            seniority=_csv(settings.theirstack_seniority, DEFAULT_SENIORITY),
        )

    def fetch_jobs(self) -> list[NormalizedJob]:
        if not self._key:
            raise TheirStackNotConfigured("TheirStack skipped: set THEIRSTACK_API_KEY in .env to enable it.")
        discovered_at = datetime.now(UTC)
        jobs: dict[str, NormalizedJob] = {}
        # Watched companies first: a handful of jobs that would not match the country filter.
        for body in self._bodies():
            limit = min(body.pop("limit"), self._budget.remaining())
            if limit <= 0:
                break  # today's credit budget is spent
            payload = self._search({**body, "limit": limit})
            data = payload.get("data") if isinstance(payload, Mapping) else None
            if not isinstance(data, list):
                raise TheirStackConnectorError("TheirStack returned an unexpected payload.")
            for raw in data:
                if not isinstance(raw, Mapping):
                    continue
                try:
                    job = _normalize_job(raw, discovered_at=discovered_at)
                except ValueError:
                    continue
                jobs.setdefault(job.external_id or job.source_url or job.title, job)
            self._budget.spend(len(data))  # one credit per job returned, valid or not
        return list(jobs.values())

    def _bodies(self) -> list[dict[str, Any]]:
        bodies = []
        if self._watch:
            bodies.append(build_search_body(limit=10, max_age_days=7, companies=self._watch, titles=self._titles))
        bodies.append(
            build_search_body(
                limit=self._page_size,
                page=self.page,
                countries=self._countries,
                titles=self._titles,
                seniority=self._seniority,
            )
        )
        return bodies

    def count_matches(self) -> int | None:
        """Total postings matching the default filters.

        Costs one credit (a single job is requested to read the total). API preview mode, which
        would be free, is not available by default on TheirStack accounts (HTTP 403).
        """

        if not self._key:
            raise TheirStackNotConfigured("TheirStack skipped: set THEIRSTACK_API_KEY in .env to enable it.")
        if self._budget.remaining() < 1:
            raise TheirStackConnectorError("TheirStack daily credit budget is spent.")
        payload = self._search(build_search_body(
                limit=1,
                include_total=True,
                countries=self._countries,
                titles=self._titles,
                seniority=self._seniority,
            ))
        self._budget.spend(1)
        metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
        total = metadata.get("total_results") if isinstance(metadata, Mapping) else None
        return total if isinstance(total, int) and not isinstance(total, bool) else None

    def _search(self, body: dict[str, Any]) -> Any:
        client = self._client or new_client(self._timeout)
        try:
            return post_json(
                client,
                SEARCH_URL,
                body,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                portal="TheirStack",
                error=TheirStackConnectorError,
                timeout=self._timeout,
            )
        finally:
            if self._client is None:
                client.close()


def _csv(value: str, default: Sequence[str]) -> tuple[str, ...]:
    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items or tuple(default)


def _normalize_job(raw: Mapping[str, Any], *, discovered_at: datetime) -> NormalizedJob:
    title = _text(raw.get("job_title"))
    listing = _https(raw.get("url")) or _https(raw.get("source_url"))
    employer = _https(raw.get("final_url"))
    if title is None or (listing is None and employer is None):
        raise ValueError("title and a posting URL are required")
    raw_id = raw.get("id")
    external_id = str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None
    company = raw.get("company")
    if isinstance(company, Mapping):
        company = company.get("name")
    location = _text(raw.get("location")) or _text(raw.get("country"))
    apply_url = employer or listing
    return NormalizedJob(
        provider=TheirStackConnector.provider,
        external_id=f"theirstack:{external_id}" if external_id else None,
        source_url=listing or employer,
        canonical_url=employer or listing,
        apply_url=apply_url,
        title=title[:255],
        company_name=(_text(company) or "")[:255] or None,
        description=html_to_text(_text(raw.get("description"))),
        location=location[:255] if location else None,
        remote_policy=RemotePolicy.REMOTE if raw.get("remote") is True else None,
        employment_type=_employment_type(raw.get("employment_statuses")),
        published_at=_published(raw.get("date_posted")),
        discovered_at=discovered_at,
        raw_metadata={
            "countryCode": _text(raw.get("country_code")),
            "seniority": _text(raw.get("seniority")),
            "technologySlugs": [t for t in raw.get("technology_slugs") or [] if isinstance(t, str)][:30] or None,
            "employerLink": employer is not None,
        },
    )


def _employment_type(value: Any) -> EmploymentType | None:
    statuses = {item.casefold() for item in value if isinstance(item, str)} if isinstance(value, list) else set()
    if "full_time" in statuses:
        return EmploymentType.FULL_TIME
    if "part_time" in statuses:
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


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _secret(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    return raw.strip()
