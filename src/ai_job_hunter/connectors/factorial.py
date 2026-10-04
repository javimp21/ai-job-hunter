"""Read and normalize public Factorial HR careers sites (server-rendered HTML).

Factorial publishes no feed, API or JSON-LD, so this connector parses only what the
pages state explicitly: the listing page (``data-*`` attributes of each job card plus
its visible title, team and work-mode cells) and, for postings whose title passes the
caller's filter, the ``styledText`` description of the detail page. The site's
``robots.txt`` is honoured before any other request.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ai_job_hunter.connectors._html import _ReadableTextParser
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy

FACTORIAL_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
FACTORIAL_REGIONS = {"com": "factorialhr.com", "es": "factorial.es"}
_COMPANY_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})$")
_MAX_LISTING_BYTES = 2 * 1024 * 1024
_MAX_DETAIL_BYTES = 1024 * 1024
_MAX_ROBOTS_BYTES = 100_000
_MAX_DESCRIPTION_CHARS = 30000
_JOB_PATH_PREFIX = "/job_posting/"
# Only explicit English work-mode labels are mapped; anything else stays unknown.
_WORK_MODES = {
    "remote": RemotePolicy.REMOTE,
    "hybrid": RemotePolicy.HYBRID,
    "onsite": RemotePolicy.ONSITE,
    "on-site": RemotePolicy.ONSITE,
    "on site": RemotePolicy.ONSITE,
}
_SCHEDULES = {"full time": EmploymentType.FULL_TIME, "part time": EmploymentType.PART_TIME}


class FactorialConnectorError(RuntimeError):
    """An HTTP, robots.txt or markup error while reading a public Factorial careers site."""


class FactorialConnector:
    """Fetch public jobs from ``{company}.factorialhr.com`` or ``{company}.factorial.es``.

    ``detail_filter`` receives each posting title; only accepted postings trigger the
    extra detail request that supplies the description, bounded by ``max_details``.
    ``None`` fetches the detail of every posting (still bounded by ``max_details``).
    """

    provider = "factorial"

    def __init__(
        self,
        company: str,
        *,
        company_name: str | None = None,
        region: str = "com",
        max_jobs: int | None = None,
        detail_filter: Callable[[str], bool] | None = None,
        max_details: int = 25,
        request_delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        normalized = company.strip()
        if not normalized:
            raise ValueError("company must not be empty")
        if not _COMPANY_SLUG.fullmatch(normalized):
            raise ValueError("company must be a Factorial subdomain label")
        region = region.strip().casefold()
        if region not in FACTORIAL_REGIONS:
            raise ValueError("region must be 'com' or 'es'")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if max_details < 0:
            raise ValueError("max_details must not be negative")
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.company = normalized
        self.region = region
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self.detail_filter = detail_filter
        self.max_details = max_details
        self.request_delay = request_delay
        self._sleep = sleep
        self._requests_made = 0
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def host(self) -> str:
        return f"{self.company.casefold()}.{FACTORIAL_REGIONS[self.region]}"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"

    def fetch_jobs(self) -> list[NormalizedJob]:
        self._requests_made = 0
        robots = self._load_robots()
        if not robots.can_fetch(FACTORIAL_USER_AGENT, f"{self.base_url}/"):
            raise FactorialConnectorError("Factorial robots.txt disallows reading the careers page.")
        listing = _parse_listing(self._request(f"{self.base_url}/", "text/html", limit=_MAX_LISTING_BYTES) or "")
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        seen: set[str] = set()
        details_fetched = 0
        for card in listing:
            if self.max_jobs is not None and len(offers) >= self.max_jobs:
                break
            external_id = self._external_id(card.url)
            if external_id is None:
                raise FactorialConnectorError("Factorial job card does not match public listing fields.")
            if external_id in seen:
                continue
            seen.add(external_id)
            detail: _Detail | None = None
            wanted = self.detail_filter is None or self.detail_filter(card.title)
            if wanted and details_fetched < self.max_details and robots.can_fetch(FACTORIAL_USER_AGENT, card.url):
                details_fetched += 1
                detail = self._get_detail(card.url)
            offers.append(self._normalize(card, detail, external_id, discovered_at))
        return offers

    def _external_id(self, url: str) -> str | None:
        """Return the job id from ``/job_posting/{slug}-{id}`` on this company's own host."""

        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if parts.scheme != "https" or (parts.hostname or "").casefold() != self.host or parts.port is not None:
            return None
        if not parts.path.startswith(_JOB_PATH_PREFIX):
            return None
        segment = parts.path[len(_JOB_PATH_PREFIX):].strip("/")
        if not segment or "/" in segment:
            return None
        tail = segment.rsplit("-", 1)[-1]
        return tail if tail.isdigit() else segment

    def _load_robots(self) -> RobotFileParser:
        text = self._request(f"{self.base_url}/robots.txt", "text/plain", limit=_MAX_ROBOTS_BYTES, allow_missing=True)
        parser = RobotFileParser()
        parser.parse(text.splitlines() if text is not None else [])  # no robots.txt: everything is allowed
        return parser

    def _get_detail(self, url: str) -> _Detail | None:
        text = self._request(url, "text/html", limit=_MAX_DETAIL_BYTES, allow_missing=True)
        return _parse_detail(text) if text is not None else None

    def _request(self, url: str, accept: str, *, limit: int, allow_missing: bool = False) -> str | None:
        """GET ``url`` without following redirects and return its text, bounded to ``limit`` bytes."""

        if self._requests_made and self.request_delay:
            self._sleep(self.request_delay)
        self._requests_made += 1
        try:
            with self._client.stream(
                "GET", url, headers={"Accept": accept, "User-Agent": FACTORIAL_USER_AGENT}
            ) as response:
                if allow_missing and response.status_code in {404, 410}:
                    # A posting can be withdrawn between the list and the detail request.
                    return None
                if response.is_redirect:
                    raise FactorialConnectorError(
                        f"Factorial redirected the request (HTTP {response.status_code}); "
                        "check the source region ('com' or 'es')."
                    )
                if response.status_code != 200:
                    raise FactorialConnectorError(f"Factorial returned HTTP {response.status_code}.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise FactorialConnectorError("Factorial page is too large.")
                encoding = response.charset_encoding or "utf-8"
        except httpx.HTTPError as error:
            raise FactorialConnectorError(
                f"Could not reach the Factorial careers site ({type(error).__name__})."
            ) from None
        try:
            return bytes(body).decode(encoding, errors="replace")
        except LookupError:
            return bytes(body).decode("utf-8", errors="replace")

    def _normalize(
        self, card: _Card, detail: _Detail | None, external_id: str, discovered_at: datetime
    ) -> NormalizedJob:
        work_mode = card.work_mode
        if card.is_remote is True:
            remote_policy: RemotePolicy | None = RemotePolicy.REMOTE
        else:
            remote_policy = _WORK_MODES.get(work_mode.casefold()) if work_mode else None
        location = (detail.location if detail is not None else None) or card.location
        if location is not None and len(location) > 255:
            location = None
        description = detail.description if detail is not None else None
        truncated = description is not None and len(description) > _MAX_DESCRIPTION_CHARS
        if truncated:
            description = description[:_MAX_DESCRIPTION_CHARS]
        return NormalizedJob(
            provider=self.provider,
            external_id=external_id,
            source_url=card.url,
            canonical_url=card.url,
            apply_url=card.url,
            title=card.title,
            company_name=self.company_name,
            description=description,
            location=location,
            remote_policy=remote_policy,
            # `data-is-remote` and the work-mode label describe the work mode only.
            employment_type=detail.employment_type if detail is not None else None,
            raw_metadata={
                "team": card.team,
                "workMode": work_mode,
                "isRemote": card.is_remote,
                "contractType": card.contract_type,
                "teamId": card.team_id,
                "locationId": card.location_id,
                "listingLocation": card.location,
                "detailFetched": detail is not None,
                "descriptionTruncated": truncated,
            },
            discovered_at=discovered_at,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FactorialConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class _Card:
    def __init__(self, attrs: dict[str, str | None], location: str | None) -> None:
        self.url = (attrs.get("data-job-postings-url") or "").strip()
        self.contract_type = _optional_text(attrs.get("data-contract-type"))
        self.team_id = _optional_text(attrs.get("data-team-id"))
        self.location_id = _optional_text(attrs.get("data-location-id"))
        remote = (attrs.get("data-is-remote") or "").strip().casefold()
        self.is_remote: bool | None = {"true": True, "false": False}.get(remote)
        self.location = location
        self.title: str = ""
        self.cells: list[str] = []

    @property
    def work_mode(self) -> str | None:
        return next((cell for cell in self.cells if cell.casefold() in _WORK_MODES), None)

    @property
    def team(self) -> str | None:
        return next((cell for cell in self.cells if cell.casefold() not in _WORK_MODES), None)


class _ListingParser(HTMLParser):
    """Collect ``li.job-offer-item`` cards and the ``h3`` office heading above each list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_Card] = []
        self._heading: list[str] | None = None
        self._last_heading: str | None = None
        self._list_location: str | None = None
        self._card: _Card | None = None
        self._field: str | None = None
        self._field_depth = 0
        self._field_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "h3":
            self._heading = []
        elif tag == "ul":
            self._list_location = self._last_heading
            self._last_heading = None
        elif tag == "li" and "job-offer-item" in classes:
            if values.get("data-job-postings-url"):
                self._card = _Card(values, self._list_location)
        elif self._card is not None and tag == "div":
            if self._field is not None:
                self._field_depth += 1
            elif "factorial__headingFontFamily" in classes:
                self._start_field("title")
            elif "text-gray-350" in classes:
                self._start_field("cell")

    def _start_field(self, name: str) -> None:
        self._field = name
        self._field_depth = 1
        self._field_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._heading is not None:
            self._last_heading = _clean(" ".join(self._heading)) or None
            self._heading = None
        elif tag == "li" and self._card is not None:
            if self._card.title and self._card.url:
                self.cards.append(self._card)
            self._card = None
            self._field = None
        elif tag == "div" and self._field is not None and self._card is not None:
            self._field_depth -= 1
            if self._field_depth == 0:
                text = _clean("".join(self._field_parts))
                if self._field == "title":
                    self._card.title = self._card.title or text
                elif text:
                    self._card.cells.append(text)
                self._field = None

    def handle_data(self, data: str) -> None:
        if self._field is not None:
            self._field_parts.append(data)
        elif self._heading is not None:
            self._heading.append(data)


class _Detail:
    def __init__(self, description: str | None, location: str | None, employment_type: EmploymentType | None) -> None:
        self.description = description
        self.location = location
        self.employment_type = employment_type


class _DetailParser(_ReadableTextParser):
    """Extract the ``styledText`` description and the first set of ``inline-block`` meta spans."""

    def __init__(self) -> None:
        super().__init__()
        self._text_depth = 0
        self._span_parts: list[str] | None = None
        self._span_depth = 0
        self.spans: list[str] = []
        self.seen_description = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if self._text_depth:
            if tag == "div":
                self._text_depth += 1
            super().handle_starttag(tag, attrs)
        elif tag == "div" and "styledText" in classes and not self.seen_description:
            self._text_depth = 1
            self.seen_description = True
        elif tag == "span" and "inline-block" in classes and "align-middle" in classes:
            self._span_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._text_depth:
            if tag == "div":
                self._text_depth -= 1
                if self._text_depth == 0:
                    return
            super().handle_endtag(tag)
        elif tag == "span" and self._span_parts is not None:
            self.spans.append("".join(self._span_parts))
            self._span_parts = None

    def handle_data(self, data: str) -> None:
        if self._text_depth:
            super().handle_data(data)
        elif self._span_parts is not None:
            self._span_parts.append(data)


def _parse_listing(html_text: str) -> list[_Card]:
    parser = _ListingParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as error:  # HTMLParser can raise on pathological markup
        raise FactorialConnectorError("Factorial listing page could not be parsed.") from error
    return parser.cards


def _parse_detail(html_text: str) -> _Detail:
    parser = _DetailParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as error:
        raise FactorialConnectorError("Factorial detail page could not be parsed.") from error
    lines = [line.strip() for line in "".join(parser.parts).replace("\xa0", " ").splitlines()]
    description = "\n".join(line for line in (re.sub(r"[ \t]+", " ", item) for item in lines) if line) or None
    location: str | None = None
    employment_type: EmploymentType | None = None
    for span in parser.spans:
        text = _clean(span)
        employment_type = employment_type or _SCHEDULES.get(text.casefold())
        head, _, rest = text.partition("(")
        if location is None and head.strip().casefold() in _WORK_MODES and rest.endswith(")"):
            location = _optional_text(rest[:-1])
    return _Detail(description, location, employment_type)


def _clean(value: str) -> str:
    return " ".join(value.split())


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
