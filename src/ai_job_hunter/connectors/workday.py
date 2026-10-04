"""Read and normalize public Workday career sites through their keyless CXS JSON API.

A Workday career site lives at ``https://<tenant>.<wdN>.myworkdayjobs.com/<site>``.
The identifier used across the project is ``"<tenant>/<site>"`` and the region is
the data-centre label ``wdN`` (for example ``wd3``). Both are validated before
they are placed in a hostname or path, so the connector can only reach
``*.myworkdayjobs.com``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy

WORKDAY_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
WORKDAY_PAGE_SIZE = 20  # Workday rejects larger "limit" values on public sites.
WORKDAY_TENANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
WORKDAY_REGION = re.compile(r"^wd[0-9]{1,3}$")
WORKDAY_SITE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_MAX_PAGES = 500
_EXTERNAL_PATH = re.compile(r"^/job/[A-Za-z0-9_%.~/-]{1,500}$")
_EMPLOYMENT_TYPES = {
    "full time": EmploymentType.FULL_TIME,
    "full-time": EmploymentType.FULL_TIME,
    "part time": EmploymentType.PART_TIME,
    "part-time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY,
    "internship": EmploymentType.INTERNSHIP,
}


class WorkdayConnectorError(RuntimeError):
    """An HTTP or payload error while reading a public Workday career site."""


def split_workday_identifier(identifier: str) -> tuple[str, str]:
    """Split ``"<tenant>/<site>"`` and validate both parts."""

    tenant, separator, site = identifier.strip().partition("/")
    if not separator or not WORKDAY_TENANT.fullmatch(tenant.casefold()) or not WORKDAY_SITE.fullmatch(site):
        raise ValueError("identifier must be '<tenant>/<site>' of a Workday career site")
    return tenant.casefold(), site


def workday_board_url(identifier: str, region: str) -> str:
    tenant, site = split_workday_identifier(identifier)
    return f"https://{tenant}.{region}.myworkdayjobs.com/{quote(site, safe='')}"


class WorkdayConnector:
    """Fetch publicly published jobs from one Workday career site.

    ``detail_filter`` receives each posting title; only accepted postings trigger
    the extra detail request that supplies the description. ``None`` fetches the
    detail of every posting (still bounded by ``max_jobs``).
    """

    provider = "workday"

    def __init__(
        self,
        identifier: str,
        *,
        region: str,
        company_name: str | None = None,
        max_jobs: int | None = None,
        detail_filter: Callable[[str], bool] | None = None,
        spain_only: bool = True,
        request_delay: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.tenant, self.site = split_workday_identifier(identifier)
        normalized_region = region.strip().casefold() if isinstance(region, str) else ""
        if not WORKDAY_REGION.fullmatch(normalized_region):
            raise ValueError("region must be a Workday data-centre label such as 'wd3'")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.region = normalized_region
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self.detail_filter = detail_filter
        self.spain_only = spain_only
        self.request_delay = request_delay
        self._sleep = sleep
        self._requests_made = 0
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._host = f"https://{self.tenant}.{self.region}.myworkdayjobs.com"
        self._api = f"{self._host}/wday/cxs/{self.tenant}/{quote(self.site, safe='')}"
        self._public = f"{self._host}/{quote(self.site, safe='')}"

    def fetch_jobs(self) -> list[NormalizedJob]:
        discovered_at = datetime.now(UTC)
        self._requests_made = 0
        offers: list[NormalizedJob] = []
        offset = 0
        total: int | None = None
        applied: dict[str, list[str]] = {}
        if self.spain_only:
            # Large employers list thousands of jobs worldwide, unsorted; the
            # site's own location facets keep the fetch to Spain.
            first = self._request("POST", f"{self._api}/jobs", json=_list_body(0, {}))
            spain = _spain_facets(first)
            if spain == {}:
                return []  # the site filters by location and has nothing in Spain
            applied = spain or {}
        for _ in range(_MAX_PAGES):
            if self.max_jobs is not None and len(offers) >= self.max_jobs:
                break
            payload = self._request("POST", f"{self._api}/jobs", json=_list_body(offset, applied))
            postings = payload.get("jobPostings") if isinstance(payload, dict) else None
            if not isinstance(postings, list):
                raise WorkdayConnectorError("Workday response must contain a jobPostings list.")
            if total is None:
                # Workday only reports "total" on the first page (0 afterwards).
                found = payload.get("total")
                if isinstance(found, bool) or not isinstance(found, int) or found < 0:
                    raise WorkdayConnectorError("Workday response does not match public posting fields.")
                total = found
            if not postings:
                break
            for index, raw in enumerate(postings):
                if self.max_jobs is not None and len(offers) >= self.max_jobs:
                    break
                if not isinstance(raw, dict):
                    raise WorkdayConnectorError(f"Workday posting at offset {offset + index} is not a JSON object.")
                try:
                    offers.append(self._build_job(raw, discovered_at))
                except (TypeError, ValueError) as error:
                    raise WorkdayConnectorError(
                        f"Workday posting at offset {offset + index} does not match public posting fields."
                    ) from error
            offset += len(postings)
            if offset >= total:
                break
        return offers

    def _build_job(self, raw: Mapping[str, Any], discovered_at: datetime) -> NormalizedJob:
        title = _optional_text(raw.get("title"))
        path = _optional_text(raw.get("externalPath"))
        if title is None or path is None or not _EXTERNAL_PATH.fullmatch(path) or ".." in path:
            raise ValueError("title and a /job/ externalPath are required")
        info: Mapping[str, Any] | None = None
        if self.detail_filter is None or self.detail_filter(title):
            info = self._get_detail(path)
        return _normalize_job(
            raw, info, public_base=self._public, path=path, company_name=self.company_name, discovered_at=discovered_at
        )

    def _get_detail(self, path: str) -> Mapping[str, Any] | None:
        payload = self._request("GET", f"{self._api}{path}", missing_ok=True)
        if payload is None:
            return None
        info = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
        if not isinstance(info, dict):
            raise WorkdayConnectorError("Workday detail must contain jobPostingInfo.")
        return info

    def _request(self, method: str, url: str, *, json: Any = None, missing_ok: bool = False) -> Any:
        if self._requests_made and self.request_delay:
            self._sleep(self.request_delay)
        self._requests_made += 1
        try:
            response = self._client.request(
                method,
                url,
                json=json,
                headers={"Accept": "application/json", "User-Agent": WORKDAY_USER_AGENT},
            )
        except httpx.RequestError as error:
            raise WorkdayConnectorError("Could not reach the Workday career site API.") from error
        if missing_ok and response.status_code in {404, 410}:
            # A posting can be withdrawn between the list and the detail request.
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise WorkdayConnectorError(
                f"Workday career site API returned HTTP {error.response.status_code}."
            ) from error
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise WorkdayConnectorError("Workday career site API response is too large.")
        try:
            return response.json()
        except ValueError as error:
            raise WorkdayConnectorError("Workday career site API returned invalid JSON.") from error

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> WorkdayConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _normalize_job(
    raw: Mapping[str, Any],
    info: Mapping[str, Any] | None,
    *,
    public_base: str,
    path: str,
    company_name: str | None,
    discovered_at: datetime,
) -> NormalizedJob:
    info = info or {}
    title = _optional_text(raw.get("title"))
    if title is None:
        raise ValueError("title is required")
    url = f"{public_base}{path}"
    req_id = _optional_text(info.get("jobReqId")) or _bullet_req_id(raw) or path.rsplit("/", 1)[-1]
    location = _optional_text(info.get("location")) or _optional_text(raw.get("locationsText"))
    if location is not None and len(location) > 255:
        location = None
    time_type = _optional_text(info.get("timeType"))
    remote = _optional_text(info.get("remoteType"))
    remote_key = remote.casefold() if remote else None
    # Only an explicit work-mode label is trusted; anything else stays unknown.
    remote_policy = {
        "remote": RemotePolicy.REMOTE,
        "fully remote": RemotePolicy.REMOTE,
        "hybrid": RemotePolicy.HYBRID,
        "on-site": RemotePolicy.ONSITE,
        "onsite": RemotePolicy.ONSITE,
    }.get(remote_key) if remote_key else None
    description = info.get("jobDescription")
    return NormalizedJob(
        provider=WorkdayConnector.provider,
        external_id=req_id,
        source_url=url,
        canonical_url=url,
        apply_url=url,
        title=title,
        company_name=company_name,
        description=html_to_text(description if isinstance(description, str) else None),
        location=location,
        remote_policy=remote_policy,
        employment_type=_EMPLOYMENT_TYPES.get(time_type.casefold()) if time_type else None,
        # The list only has relative text ("Posted 3 Days Ago"); "startDate" is the
        # role start, not the publication date. "30+ Days" counts as 31.
        published_at=_posted_on(raw.get("postedOn"), discovered_at),
        raw_metadata={
            "req_id": req_id,
            "posted_on": _optional_text(raw.get("postedOn")),
            "locations_text": _optional_text(raw.get("locationsText")),
            "time_type": time_type,
            "remote_type": remote,
            "country": _country(info),
        },
        discovered_at=discovered_at,
    )


def _list_body(offset: int, applied: Mapping[str, list[str]]) -> dict[str, Any]:
    return {"limit": WORKDAY_PAGE_SIZE, "offset": offset, "searchText": "", "appliedFacets": dict(applied)}


_SPAIN_LABELS = re.compile(r"\b(?:spain|españa|espana|madrid|barcelona)\b", re.IGNORECASE)
_COUNTRY_FACETS = {"locationcountry", "country"}


def _spain_facets(payload: Any) -> dict[str, list[str]] | None:
    """Facet ids that select Spain: the country facet when present, else Spanish locations.

    ``None`` means the site has no location facets (fetch everything); ``{}``
    means it has location facets but nothing in Spain.
    """

    facets = payload.get("facets") if isinstance(payload, dict) else None
    country: dict[str, list[str]] = {}
    places: dict[str, list[str]] = {}
    has_location = False

    def walk(items: Any, parameter: str | None) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("facetParameter") if isinstance(item.get("facetParameter"), str) else parameter
            nonlocal has_location
            if name and ("location" in name.casefold() or name.casefold() in _COUNTRY_FACETS):
                has_location = True
            if isinstance(item.get("values"), list):
                walk(item["values"], name)
                continue
            label, value = item.get("descriptor"), item.get("id")
            if not (name and isinstance(label, str) and isinstance(value, str) and _SPAIN_LABELS.search(label)):
                continue
            if name.casefold() in _COUNTRY_FACETS:
                if label.strip().casefold() in {"spain", "españa", "espana"}:
                    country.setdefault(name, []).append(value)
            elif "location" in name.casefold():
                places.setdefault(name, []).append(value)

    walk(facets, None)
    if not has_location:
        return None
    return country or places


_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)


def _posted_on(value: Any, now: datetime) -> datetime | None:
    match = _POSTED.search(value) if isinstance(value, str) else None
    if match is None:
        return None
    word = match.group(1).casefold()
    days = 0 if word == "today" else 1 if word == "yesterday" else int(match.group(2))
    if "+" in match.group(0):
        days += 1  # "30+ Days Ago" means more than 30 days
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=days)


def _bullet_req_id(raw: Mapping[str, Any]) -> str | None:
    bullets = raw.get("bulletFields")
    if isinstance(bullets, list):
        for item in bullets:
            text = _optional_text(item)
            if text:
                return text
    return None


def _country(info: Mapping[str, Any]) -> str | None:
    country = info.get("country")
    return _optional_text(country.get("descriptor")) if isinstance(country, dict) else None


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
