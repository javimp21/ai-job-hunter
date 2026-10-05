"""Read Amazon's public job search (``amazon.jobs/en/search.json``), the keyless JSON the site itself uses.

Scope is deliberately narrow: software-development jobs in Spain, Ireland, Luxembourg, the
Netherlands and Switzerland. ``robots.txt`` is read first (any error other than 404 fails
closed) and must allow the search endpoint; requests are paged, one per ``request_delay``
seconds, never redirected to another host. No remote eligibility is derived: Amazon's
payload has no work-mode field, so ``remote_policy`` stays unknown.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._robots import RobotsRules
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob

AMAZON_JOBS_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
AMAZON_JOBS_IDENTIFIER = "amazon.jobs"
AMAZON_JOBS_HOST = "www.amazon.jobs"
AMAZON_JOBS_SEARCH_PATH = "/en/search.json"
# ISO 3166-1 alpha-3 codes used by the search's ``normalized_country_code[]`` filter.
AMAZON_JOBS_COUNTRIES = ("ESP", "IRL", "LUX", "NLD", "CHE")
AMAZON_JOBS_CATEGORY = "software-development"
_PAGE_SIZE = 100
_MAX_PAGES = 5
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_ROBOTS_BYTES = 100_000
_MAX_DESCRIPTION_CHARS = 30000


class AmazonJobsConnectorError(RuntimeError):
    """An HTTP, robots.txt or payload error while reading Amazon's public job search."""


class AmazonJobsConnector:
    """Fetch Amazon software-development jobs in the target countries."""

    provider = "amazon_jobs"

    def __init__(
        self,
        identifier: str = AMAZON_JOBS_IDENTIFIER,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        countries: tuple[str, ...] = AMAZON_JOBS_COUNTRIES,
        request_delay: float = 1.0,
        sleep: Callable[[float], None] | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        if identifier.strip().casefold() != AMAZON_JOBS_IDENTIFIER:
            raise ValueError(f"identifier must be '{AMAZON_JOBS_IDENTIFIER}'")
        if not countries or any(code not in AMAZON_JOBS_COUNTRIES for code in countries):
            raise ValueError(f"countries must be a non-empty subset of {', '.join(AMAZON_JOBS_COUNTRIES)}")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.company_name = company_name.strip() if company_name and company_name.strip() else "Amazon"
        self.max_jobs = max_jobs
        self.countries = countries
        self.request_delay = request_delay
        self._sleep = sleep or time.sleep
        self._requests_made = 0
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_jobs(self) -> list[NormalizedJob]:
        self._requests_made = 0
        text = self._request(f"https://{AMAZON_JOBS_HOST}/robots.txt", {"Accept": "text/plain"}, _MAX_ROBOTS_BYTES, True)
        robots = RobotsRules(text, "AI-Job-Hunter")
        search_url = f"https://{AMAZON_JOBS_HOST}{AMAZON_JOBS_SEARCH_PATH}"
        if not robots.can_fetch(search_url):
            raise AmazonJobsConnectorError("Amazon robots.txt disallows the job search.")
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        seen: set[str] = set()
        offset = 0
        for _page in range(_MAX_PAGES):
            payload = self._search(search_url, offset)
            jobs = payload.get("jobs")
            if not isinstance(jobs, list):
                raise AmazonJobsConnectorError("Amazon returned an unexpected job search payload.")
            for item in jobs:
                offer = self._normalize(item, discovered_at) if isinstance(item, dict) else None
                if offer is None or offer.external_id in seen:
                    continue
                seen.add(offer.external_id or "")
                offers.append(offer)
                if self.max_jobs is not None and len(offers) >= self.max_jobs:
                    return offers
            offset += _PAGE_SIZE
            hits = payload.get("hits")
            if not jobs or not isinstance(hits, int) or offset >= hits:
                break
        return offers

    def _search(self, url: str, offset: int) -> dict[str, Any]:
        params: list[tuple[str, str]] = [("category[]", AMAZON_JOBS_CATEGORY)]
        params.extend(("normalized_country_code[]", code) for code in self.countries)
        params.extend((("result_limit", str(_PAGE_SIZE)), ("offset", str(offset))))
        body = self._request(url, {"Accept": "application/json"}, _MAX_RESPONSE_BYTES, False, params)
        try:
            payload = httpx.Response(200, content=(body or "").encode("utf-8")).json()
        except ValueError:
            raise AmazonJobsConnectorError("Amazon returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise AmazonJobsConnectorError("Amazon returned an unexpected job search payload.")
        return payload

    def _normalize(self, item: dict[str, Any], discovered_at: datetime) -> NormalizedJob | None:
        country = item.get("country_code")
        if country not in self.countries:  # the filter is Amazon's; never trust it for scope
            return None
        job_id = _text(item.get("id_icims")) or _text(item.get("id"))
        path = _text(item.get("job_path"))
        title = _text(item.get("title"))
        if job_id is None or title is None or path is None or not path.startswith("/") or len(title) > 255:
            return None
        url = f"https://{AMAZON_JOBS_HOST}{path}"
        sections = [
            html_to_text(_text(item.get("description"))),
            _titled("Basic qualifications", html_to_text(_text(item.get("basic_qualifications")))),
            _titled("Preferred qualifications", html_to_text(_text(item.get("preferred_qualifications")))),
        ]
        description = "\n\n".join(section for section in sections if section) or None
        truncated = description is not None and len(description) > _MAX_DESCRIPTION_CHARS
        if truncated:
            description = description[:_MAX_DESCRIPTION_CHARS]
        location = _text(item.get("normalized_location")) or _text(item.get("location"))
        schedule = (_text(item.get("job_schedule_type")) or "").casefold()
        employment_type = (
            EmploymentType.INTERNSHIP
            if item.get("is_intern") is True
            else {"full-time": EmploymentType.FULL_TIME, "part-time": EmploymentType.PART_TIME}.get(schedule)
        )
        try:
            return NormalizedJob(
                provider=self.provider,
                external_id=job_id,
                source_url=url,
                canonical_url=url,
                apply_url=url,
                title=title,
                company_name=self.company_name,
                description=description,
                location=location if location and len(location) <= 255 else None,
                employment_type=employment_type,
                published_at=_parse_posted_date(item.get("posted_date")),
                discovered_at=discovered_at,
                raw_metadata={
                    "countryCode": country,
                    "jobCategory": _text(item.get("job_category")),
                    "businessCategory": _text(item.get("business_category")),
                    "team": _text(item.get("team")),
                    "legalEntity": _text(item.get("company_name")),
                    "scheduleType": _text(item.get("job_schedule_type")),
                    "isIntern": item.get("is_intern") if isinstance(item.get("is_intern"), bool) else None,
                    "descriptionTruncated": truncated,
                },
            )
        except ValueError:
            return None

    def _request(
        self,
        url: str,
        headers: dict[str, str],
        limit: int,
        allow_missing: bool,
        params: list[tuple[str, str]] | None = None,
    ) -> str | None:
        if self._requests_made and self.request_delay:
            self._sleep(self.request_delay)
        self._requests_made += 1
        try:
            with self._client.stream(
                "GET", url, params=params, headers={**headers, "User-Agent": AMAZON_JOBS_USER_AGENT},
                follow_redirects=False,
            ) as response:
                if allow_missing and response.status_code in {404, 410}:
                    return None
                if response.status_code != 200:  # redirects included: nothing is followed
                    raise AmazonJobsConnectorError(f"Amazon returned HTTP {response.status_code}.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise AmazonJobsConnectorError("Amazon response is too large.")
                encoding = response.charset_encoding or "utf-8"
        except httpx.HTTPError as error:
            raise AmazonJobsConnectorError(f"Could not reach Amazon jobs ({type(error).__name__}).") from None
        try:
            return bytes(body).decode(encoding, errors="replace")
        except LookupError:
            return bytes(body).decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> AmazonJobsConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _parse_posted_date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(" ".join(value.split()), "%B %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _titled(title: str, text: str | None) -> str | None:
    return f"{title}\n{text}" if text else None


def _text(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None
