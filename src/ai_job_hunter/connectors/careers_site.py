"""Read employer careers sites that publish schema.org ``JobPosting`` JSON-LD.

Many careers sites that run no supported ATS still list every job page in a sitemap and
describe each page with ``JobPosting`` JSON-LD (for Google for Jobs). This connector uses
only those two structured sources: ``robots.txt`` (read first; any error other than 404
fails closed), the sitemap(s) it declares or ``/sitemap.xml`` (indexes followed, bounded),
and the JSON-LD of job pages. Pages without a ``JobPosting`` are skipped, never scraped from
HTML, and remote eligibility is never inferred (``TELECOMMUTE`` only sets the work mode).

The identifier is the careers base URL without scheme: ``host`` or ``host/path``. Only that
host is ever contacted; redirects are followed only within it.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import html
from html import unescape as html_unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from pydantic import ValidationError

from ai_job_hunter.connectors._html import html_to_text
from ai_job_hunter.connectors._robots import RobotsRules
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy, SalaryPeriod

CAREERS_SITE_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"
_ROBOTS_TOKEN = "AI-Job-Hunter"
_HOST = re.compile(r"^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,62})(?:\.[a-z0-9](?:[a-z0-9-]{0,62}))+$")
_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~%-]{0,99}$")
_MAX_ROBOTS_BYTES = 200_000
_MAX_SITEMAP_BYTES = 8 * 1024 * 1024
_MAX_PAGE_BYTES = 2 * 1024 * 1024
_MAX_SITEMAP_FILES = 12
_MAX_SITEMAP_URLS = 50_000
_MAX_REDIRECTS = 3
_MAX_DESCRIPTION_CHARS = 30000
_MAX_CRAWL_DELAY = 10.0
_MAX_JSON_LD_SCRIPTS = 30
_JOB_SEGMENTS = frozenset(
    {
        "job", "jobs", "vacancy", "vacancies", "position", "positions", "opening", "openings",
        "posting", "postings", "requisition", "jobdetail", "jobdetails", "job-detail",
        "empleo", "empleos", "oferta", "ofertas", "vacante", "vacantes", "oferta-empleo",
        "offre", "offres", "emploi", "emplois", "stelle", "stellen", "stellenangebot",
        "stellenangebote", "vacature", "vacatures",
    }
)
_NON_PAGE_EXTENSIONS = frozenset(
    {"pdf", "jpg", "jpeg", "png", "gif", "svg", "webp", "xml", "json", "zip", "doc", "docx", "css", "js", "txt"}
)
_EMPLOYMENT_TYPES = {
    "FULL_TIME": EmploymentType.FULL_TIME,
    "PART_TIME": EmploymentType.PART_TIME,
    "CONTRACTOR": EmploymentType.CONTRACT,
    "TEMPORARY": EmploymentType.TEMPORARY,
    "INTERN": EmploymentType.INTERNSHIP,
    "OTHER": EmploymentType.OTHER,
}
_SALARY_PERIODS = {
    "HOUR": SalaryPeriod.HOUR,
    "DAY": SalaryPeriod.DAY,
    "WEEK": SalaryPeriod.WEEK,
    "MONTH": SalaryPeriod.MONTH,
    "YEAR": SalaryPeriod.YEAR,
    "ANNUAL": SalaryPeriod.YEAR,
}


# Job pages without JSON-LD (see CareersSiteConnector._labelled_page).
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"<a\b[^>]*\bhref\s*=\s*[\"']([^\"'#]+)", re.IGNORECASE)
_MAIN = re.compile(r"<main\b[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL)
_LABEL_FIELDS = {
    "ubicación": "location", "ubicacion": "location", "localización": "location", "localizacion": "location",
    "location": "location", "lugar de trabajo": "location",
    "experiencia": "experience", "experience": "experience", "años de experiencia": "experience",
    "tipo de contrato": "contract", "contrato": "contract", "jornada": "contract", "contract": "contract",
    "employment type": "contract",
}
_LABELLED_LINE = re.compile(
    r"^\W{0,4}(" + "|".join(re.escape(label) for label in sorted(_LABEL_FIELDS, key=len, reverse=True)) + r")\s*:\s*(\S.{0,200})$",
    re.IGNORECASE,
)
_CONTRACT_WORDS = (
    (("completa", "full"), EmploymentType.FULL_TIME),
    (("parcial", "part"), EmploymentType.PART_TIME),
    (("prácticas", "practicas", "intern", "beca"), EmploymentType.INTERNSHIP),
)


class CareersSiteConnectorError(RuntimeError):
    """An HTTP, robots.txt or sitemap error while reading a public careers site."""


def split_careers_identifier(identifier: str) -> tuple[str, str]:
    """Split ``host[/path]`` into a validated lower-case host and a ``/path`` prefix (``""`` for none)."""

    host, _, rest = identifier.strip().strip("/").partition("/")
    host = host.casefold()
    if not _HOST.fullmatch(host) or re.fullmatch(r"[0-9.]+", host):
        raise ValueError("identifier must be a careers site host such as 'careers.example.com' or 'example.com/jobs'")
    segments = [part for part in rest.split("/") if part]
    if len(segments) > 6 or not all(_PATH_SEGMENT.fullmatch(part) for part in segments):
        raise ValueError("identifier path must be a short sequence of plain path segments")
    return host, "".join(f"/{part}" for part in segments)


def careers_site_board_url(identifier: str) -> str:
    host, path = split_careers_identifier(identifier)
    return f"https://{host}{path}"


def careers_site_identifier_from_url(url: str, *, host_only: bool = False) -> str | None:
    """Derive ``host[/path]`` from a careers page URL; ``None`` for anything but plain https/http URLs.

    The path is cut before the first job-page marker (``/job/..``) and a trailing file name, so a
    link to one posting identifies the whole careers site. ``host_only`` drops the path entirely.
    """

    try:
        parts = urlsplit(url.strip() if "://" in url else f"https://{url.strip()}")
        host = (parts.hostname or "").casefold().rstrip(".")
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or port not in {None, 80, 443} or parts.username or parts.password:
        return None
    segments = [unquote(part) for part in parts.path.split("/") if part]
    kept: list[str] = []
    for segment in segments:
        if segment.casefold() in _JOB_SEGMENTS or "." in segment:
            break
        kept.append(segment)
    path = "" if host_only else "".join(f"/{part}" for part in kept[:4])
    identifier = f"{host}{path}"
    try:
        split_careers_identifier(identifier)
    except ValueError:
        return None
    return identifier


def _listing_identifier(url: str) -> str | None:
    """``host/path`` of a listing page whose path ends in a job marker (``/ofertas/``, ``/jobs``)."""

    try:
        parts = urlsplit(url.strip() if "://" in url else f"https://{url.strip()}")
    except ValueError:
        return None
    segments = [unquote(part) for part in parts.path.split("/") if part]
    if not segments or len(segments) > 4 or segments[-1].casefold() not in _JOB_SEGMENTS:
        return None
    identifier = f"{(parts.hostname or '').casefold()}/" + "/".join(segments)
    try:
        split_careers_identifier(identifier)
    except ValueError:
        return None
    return identifier


def job_url_title(url: str) -> str:
    """Best-effort title words from a job URL slug (used only as a cheap pre-fetch gate)."""

    segments = [unquote(part) for part in urlsplit(url).path.split("/") if part]
    for index, segment in enumerate(segments):
        if segment.casefold() in _JOB_SEGMENTS:
            rest = [part for part in segments[index + 1:] if not part.isdigit()]
            words = [re.sub(r"[-_+]+", " ", part).strip() for part in rest]
            return max(words, key=lambda text: (len(text.split()), len(text)), default="")
    return ""


@dataclass(frozen=True, slots=True)
class CareersSiteProbe:
    """Outcome of sampling a careers site for ``JobPosting`` support."""

    identifier: str
    job_urls: int
    sampled: int
    postings: int

    @property
    def supported(self) -> bool:
        return self.postings > 0


class CareersSiteConnector:
    """Fetch jobs of one careers site from its sitemap and the JSON-LD of its job pages.

    ``known_urls`` are job page URLs already stored by the caller: they are never fetched
    again. At most ``max_details`` unseen pages are fetched per run (newest sitemap
    ``lastmod`` first), one request every ``request_delay`` seconds (more when robots.txt
    asks for a longer ``Crawl-delay``). ``url_filter`` can skip clearly irrelevant URLs
    before any request; ``None`` accepts every job-looking URL.
    """

    provider = "careers_site"

    def __init__(
        self,
        identifier: str,
        *,
        company_name: str | None = None,
        max_jobs: int | None = None,
        known_urls: Collection[str] = (),
        url_filter: Callable[[str], bool] | None = None,
        max_details: int = 25,
        request_delay: float = 1.0,
        sleep: Callable[[float], None] | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.host, self.path_prefix = split_careers_identifier(identifier)
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be a positive integer")
        if max_details < 0:
            raise ValueError("max_details must not be negative")
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.company_name = _optional_text(company_name)
        self.max_jobs = max_jobs
        self.known_urls = {_normalize_url(url) for url in known_urls}
        self.url_filter = url_filter
        self.max_details = max_details
        self.request_delay = request_delay
        self._delay = request_delay
        self._sleep = sleep or time.sleep
        self._requests_made = 0
        self.stats: dict[str, int] = {}
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def identifier(self) -> str:
        return f"{self.host}{self.path_prefix}"

    @property
    def origin(self) -> str:
        return f"https://{self.host}"

    def fetch_jobs(self) -> list[NormalizedJob]:
        robots, urls = self._discover()
        discovered_at = datetime.now(UTC)
        offers: list[NormalizedJob] = []
        for url, lastmod in self._unseen(urls, robots)[: self.max_details]:
            if self.max_jobs is not None and len(offers) >= self.max_jobs:
                break
            job = self._fetch_posting(url, lastmod, discovered_at)
            if job is not None:
                offers.append(job)
        return offers

    def probe(self, sample: int = 3) -> CareersSiteProbe:
        """Fetch ``sample`` evenly spread job pages and count those carrying a ``JobPosting``."""

        robots, urls = self._discover()
        candidates = self._unseen(urls, robots)
        if len(candidates) > sample:
            step = len(candidates) / sample
            candidates = [candidates[int(index * step)] for index in range(sample)]
        postings = sum(
            self._fetch_posting(url, lastmod, datetime.now(UTC)) is not None for url, lastmod in candidates
        )
        return CareersSiteProbe(self.identifier, self.stats.get("job_urls", 0), len(candidates), postings)

    def _discover(self) -> tuple[RobotsRules, list[tuple[str, str | None]]]:
        self._requests_made = 0
        self._delay = self.request_delay
        self.stats = {
            "sitemap_urls": 0, "job_urls": 0, "known": 0, "fetched": 0,
            "no_jobposting": 0, "expired": 0, "parsed": 0,
        }
        robots = self._load_robots()
        urls = self._collect_job_urls(robots)
        self.stats["job_urls"] = len(urls)
        return robots, urls

    def _unseen(self, urls: list[tuple[str, str | None]], robots: RobotsRules) -> list[tuple[str, str | None]]:
        wanted: list[tuple[str, str | None]] = []
        for url, lastmod in urls:
            if _normalize_url(url) in self.known_urls:
                self.stats["known"] += 1
            elif robots.can_fetch(url) and (self.url_filter is None or self.url_filter(url)):
                wanted.append((url, lastmod))
        wanted.sort(key=lambda item: item[1] or "", reverse=True)  # newest first; stable for equal dates
        return wanted

    # -- robots and sitemaps ------------------------------------------------------------

    def _load_robots(self) -> RobotsRules:
        text = self._request(f"{self.origin}/robots.txt", "text/plain", limit=_MAX_ROBOTS_BYTES, allow_missing=True)
        if text is not None and text.lstrip().startswith("<"):
            # A bot-protection or error page served in place of robots.txt: the rules are unknown.
            raise CareersSiteConnectorError("Careers site robots.txt is not a text file (HTML was returned).")
        rules = RobotsRules(text, _ROBOTS_TOKEN)  # no robots.txt (404): everything is allowed
        if rules.crawl_delay is not None and rules.crawl_delay > 0:
            self._delay = max(self.request_delay, min(rules.crawl_delay, _MAX_CRAWL_DELAY))
        return rules

    def _collect_job_urls(self, robots: RobotsRules) -> list[tuple[str, str | None]]:
        pending = [self._own_https(url) for url in robots.sitemaps]
        pending = [url for url in dict.fromkeys(pending) if url is not None] or [f"{self.origin}/sitemap.xml"]
        seen_sitemaps: set[str] = set()
        found: dict[str, str | None] = {}
        while pending and len(seen_sitemaps) < _MAX_SITEMAP_FILES:
            sitemap_url = pending.pop(0)
            if sitemap_url in seen_sitemaps or not robots.can_fetch(sitemap_url):
                continue
            seen_sitemaps.add(sitemap_url)
            body = self._request(sitemap_url, "application/xml,text/xml", limit=_MAX_SITEMAP_BYTES, allow_missing=True)
            if body is None:
                continue
            kind, entries = _parse_sitemap(body)
            for loc, lastmod in entries:
                if kind == "index":
                    child = self._own_https(loc)
                    if child is not None:
                        pending.append(child)
                    continue
                self.stats["sitemap_urls"] += 1
                if self.stats["sitemap_urls"] > _MAX_SITEMAP_URLS:
                    raise CareersSiteConnectorError("Careers site sitemap lists too many URLs.")
                if self._looks_like_job_url(loc):
                    found.setdefault(loc, lastmod)
        if not found and self.path_prefix:
            found = dict.fromkeys(self._listing_job_urls(robots))
        return list(found.items())

    def _listing_job_urls(self, robots: RobotsRules) -> list[str]:
        """Links one level below the careers path, read from that listing page itself.

        Used when the sitemap lists no job pages (e.g. ``quantia.es/ofertas`` lists its
        offers only on ``/ofertas/``). Only same-host links under the path are kept.
        """

        listing = f"{self.origin}{self.path_prefix}/"
        if not robots.can_fetch(listing):
            return []
        body = self._request(listing, "text/html,application/xhtml+xml", limit=_MAX_PAGE_BYTES, allow_missing=True)
        if body is None:
            return []
        prefix = [part.casefold() for part in self.path_prefix.split("/") if part]
        urls: list[str] = []
        for href in _HREF.findall(body):
            url = self._own_https(urljoin(listing, html_unescape(href)))
            if url is None:
                continue
            parts = urlsplit(url)
            segments = [part for part in parts.path.split("/") if part]
            if parts.query or len(segments) != len(prefix) + 1:
                continue
            if [part.casefold() for part in segments[: len(prefix)]] != prefix:
                continue
            if "." in segments[-1] and segments[-1].rsplit(".", 1)[-1].casefold() in _NON_PAGE_EXTENSIONS:
                continue
            urls.append(parts._replace(fragment="").geturl())
        return list(dict.fromkeys(urls))

    def _own_https(self, url: str) -> str | None:
        """Return ``url`` as https on this site's host (a declared ``http://`` sitemap is upgraded)."""

        try:
            parts = urlsplit(url.strip())
            host, port = (parts.hostname or "").casefold(), parts.port
        except ValueError:
            return None
        if host != self.host or parts.scheme not in {"http", "https"} or port not in {None, 80, 443}:
            return None
        return parts._replace(scheme="https", netloc=self.host, fragment="").geturl()

    def _looks_like_job_url(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
            host, port = (parts.hostname or "").casefold(), parts.port
        except ValueError:
            return False
        if parts.scheme != "https" or host != self.host or port is not None or len(url) > 2048:
            return False
        segments = [part for part in parts.path.split("/") if part]
        prefix = [part for part in self.path_prefix.split("/") if part]
        if [part.casefold() for part in segments[: len(prefix)]] != [part.casefold() for part in prefix]:
            return False
        if segments and "." in segments[-1] and segments[-1].rsplit(".", 1)[-1].casefold() in _NON_PAGE_EXTENSIONS:
            return False
        rest = [unquote(part).casefold() for part in segments[len(prefix):]]
        return any(segment in _JOB_SEGMENTS and index < len(rest) - 1 for index, segment in enumerate(rest))

    # -- job pages ----------------------------------------------------------------------

    def _fetch_posting(self, url: str, lastmod: str | None, discovered_at: datetime) -> NormalizedJob | None:
        html_text = self._request(url, "text/html,application/xhtml+xml", limit=_MAX_PAGE_BYTES, allow_missing=True)
        self.stats["fetched"] += 1
        postings = (_job_postings(html_text) or _microdata_postings(html_text)) if html_text is not None else []
        if not postings and html_text is not None:
            # Small sites (e.g. WordPress) without JSON-LD: accept only a page shaped like one job ad.
            job = self._labelled_page(html_text, url, lastmod, discovered_at)
            if job is not None:
                self.stats["parsed"] += 1
                return job
        if len(postings) != 1:  # none (not a job page) or several (a listing page)
            self.stats["no_jobposting"] += 1
            return None
        job = self._normalize(postings[0], url, lastmod, discovered_at)
        if job is None:
            self.stats["expired" if _is_expired(postings[0], discovered_at) else "no_jobposting"] += 1
            return None
        self.stats["parsed"] += 1
        return job

    def _normalize(
        self, posting: dict[str, Any], url: str, lastmod: str | None, discovered_at: datetime
    ) -> NormalizedJob | None:
        if _is_expired(posting, discovered_at):
            return None
        title = _optional_text(posting.get("title")) or _optional_text(posting.get("name"))
        if title is None or len(title) > 255:
            return None
        description = html_to_text(posting.get("description")) if isinstance(posting.get("description"), str) else None
        truncated = description is not None and len(description) > _MAX_DESCRIPTION_CHARS
        if truncated:
            description = description[:_MAX_DESCRIPTION_CHARS]
        location_types = _as_list(posting.get("jobLocationType"))
        remote_policy = (
            RemotePolicy.REMOTE
            if any(isinstance(item, str) and item.strip().upper() == "TELECOMMUTE" for item in location_types)
            else None
        )
        applicant_regions = _applicant_location_names(posting.get("applicantLocationRequirements"))
        location = _location_text(posting.get("jobLocation")) or ", ".join(applicant_regions) or None
        if location is not None and len(location) > 255:
            location = None
        salary = _salary(posting.get("baseSalary"))
        organization = _organization_name(posting.get("hiringOrganization"))
        clean_url = _normalize_url(url)
        external_id = f"{self.host}{urlsplit(clean_url).path}"
        if urlsplit(clean_url).query:
            external_id += f"?{urlsplit(clean_url).query}"
        if len(external_id) > 500:
            external_id = f"{self.host}/sha256:{hashlib.sha256(clean_url.encode()).hexdigest()[:32]}"
        try:
            return NormalizedJob(
                provider=self.provider,
                external_id=external_id,
                source_url=clean_url,
                canonical_url=clean_url,
                apply_url=clean_url,
                title=title,
                company_name=self.company_name or organization,
                description=description,
                location=location,
                remote_policy=remote_policy,
                # TELECOMMUTE describes the work mode only; where a remote hire may live stays unknown.
                employment_type=_employment_type(posting.get("employmentType")),
                published_at=_parse_datetime(posting.get("datePosted"), discovered_at),
                discovered_at=discovered_at,
                raw_metadata={
                    "identifier": _identifier_value(posting.get("identifier")),
                    "validThrough": _optional_text(posting.get("validThrough")),
                    "employmentType": posting.get("employmentType") if isinstance(posting.get("employmentType"), (str, list)) else None,
                    "jobLocationType": [item for item in location_types if isinstance(item, str)] or None,
                    "applicantLocationRequirements": applicant_regions or None,
                    "hiringOrganization": organization,
                    "sitemapLastmod": lastmod,
                    "descriptionTruncated": truncated,
                    **(salary.metadata if salary else {}),
                },
                **(salary.fields if salary else {}),
            )
        except ValidationError:
            return None

    def _labelled_page(
        self, html_text: str, url: str, lastmod: str | None, discovered_at: datetime
    ) -> NormalizedJob | None:
        """A job page without JSON-LD: one ``<h1>`` title plus explicit "Label: value" lines.

        At least two different labels (location, experience, contract) must each appear
        exactly once, which a single job ad has and listings, blog posts or shop pages do
        not. Values are copied as written; nothing is inferred.
        """

        headings = [html_to_text(match) for match in _H1.findall(html_text)]
        headings = [heading.strip() for heading in headings if heading and heading.strip()]
        if len(headings) != 1 or len(headings[0]) > 255:
            return None
        mains = _MAIN.findall(html_text)
        body = html_to_text(mains[0] if len(mains) == 1 else html_text) or ""
        labels: dict[str, list[str]] = {}
        for line in body.splitlines():
            match = _LABELLED_LINE.match(line.strip())
            if match:
                field = _LABEL_FIELDS[match.group(1).casefold()]
                labels.setdefault(field, []).append(match.group(2).strip())
        found = {field: values[0] for field, values in labels.items() if len(values) == 1}
        if len(found) < 2 or any(len(values) > 1 for values in labels.values()):
            return None
        location = found.get("location")
        contract = (found.get("contract") or "").casefold()
        employment_type = next((kind for words, kind in _CONTRACT_WORDS if any(w in contract for w in words)), None)
        description = body[:_MAX_DESCRIPTION_CHARS] or None
        clean_url = _normalize_url(url)
        try:
            return NormalizedJob(
                provider=self.provider,
                external_id=f"{self.host}{urlsplit(clean_url).path}"[:500],
                source_url=clean_url,
                canonical_url=clean_url,
                apply_url=clean_url,
                title=headings[0],
                company_name=self.company_name,
                description=description,
                location=location[:255] if location else None,
                employment_type=employment_type,
                published_at=None,  # the sitemap lastmod is a modification date, not publication
                discovered_at=discovered_at,
                raw_metadata={"format": "labelled_page", "labels": found, "sitemapLastmod": lastmod},
            )
        except ValidationError:
            return None

    # -- HTTP ---------------------------------------------------------------------------

    def _request(self, url: str, accept: str, *, limit: int, allow_missing: bool = False) -> str | None:
        """GET ``url`` (following redirects only within this host) and return its text, bounded to ``limit`` bytes."""

        for _hop in range(_MAX_REDIRECTS + 1):
            if self._requests_made and self._delay:
                self._sleep(self._delay)
            self._requests_made += 1
            try:
                with self._client.stream(
                    "GET", url, headers={"Accept": accept, "User-Agent": CAREERS_SITE_USER_AGENT}, follow_redirects=False
                ) as response:
                    if allow_missing and response.status_code in {404, 410}:
                        return None
                    if response.is_redirect:
                        target = self._own_https(urljoin(url, response.headers.get("location", "")))
                        if target is None:
                            raise CareersSiteConnectorError(
                                f"Careers site redirected to another host (HTTP {response.status_code})."
                            )
                        url = target
                        continue
                    if response.status_code != 200:
                        raise CareersSiteConnectorError(f"Careers site returned HTTP {response.status_code}.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > limit:
                            raise CareersSiteConnectorError("Careers site response is too large.")
                    encoding = response.charset_encoding or "utf-8"
            except httpx.HTTPError as error:
                raise CareersSiteConnectorError(
                    f"Could not reach the careers site ({type(error).__name__})."
                ) from None
            try:
                return bytes(body).decode(encoding, errors="replace")
            except LookupError:
                return bytes(body).decode("utf-8", errors="replace")
        raise CareersSiteConnectorError("Careers site redirected too many times.")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CareersSiteConnector:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def probe_careers_site(
    url: str,
    *,
    client: httpx.Client | None = None,
    sample: int = 3,
    request_delay: float = 1.0,
    sleep: Callable[[float], None] | None = None,
) -> CareersSiteProbe | None:
    """Check whether the careers site behind ``url`` publishes ``JobPosting`` JSON-LD on its job pages.

    Tries the URL's own path first, then the bare host. Returns the first probe that sampled
    at least one posting, else ``None`` (blocked, no sitemap, no job pages or no JSON-LD).
    """

    candidates = [
        identifier
        for identifier in dict.fromkeys(
            (
                careers_site_identifier_from_url(url),
                careers_site_identifier_from_url(url, host_only=True),
                _listing_identifier(url),  # e.g. quantia.es/ofertas: offers linked only from that page
            )
        )
        if identifier is not None
    ]
    for identifier in candidates:
        connector = CareersSiteConnector(
            identifier, client=client, request_delay=request_delay, sleep=sleep
        )
        try:
            probe = connector.probe(sample)
        except CareersSiteConnectorError:
            continue
        finally:
            connector.close()
        if probe.supported:
            return probe
    return None


# -- sitemap parsing --------------------------------------------------------------------


def _parse_sitemap(text: str) -> tuple[str, list[tuple[str, str | None]]]:
    """Return ``("index" | "urlset", [(loc, lastmod)])``; DTDs and entities are refused outright."""

    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise CareersSiteConnectorError("Careers site sitemap uses a DTD, which is not supported.")
    try:
        root = ElementTree.fromstring(text.lstrip("﻿").encode("utf-8"))
    except ElementTree.ParseError:
        raise CareersSiteConnectorError("Careers site sitemap is not valid XML.") from None
    kind = "index" if _local_name(root.tag) == "sitemapindex" else "urlset"
    entries: list[tuple[str, str | None]] = []
    for node in root:
        loc = lastmod = None
        for child in node:
            name = _local_name(child.tag)
            if name == "loc" and child.text and child.text.strip():
                loc = child.text.strip()
            elif name == "lastmod" and child.text and child.text.strip():
                lastmod = child.text.strip()
        if loc:
            entries.append((loc, lastmod))
    return kind, entries


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold() if isinstance(tag, str) else ""


# -- JSON-LD ----------------------------------------------------------------------------


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and len(self.scripts) < _MAX_JSON_LD_SCRIPTS:
            kind = (dict(attrs).get("type") or "").split(";")[0].strip().casefold()
            self._buffer = [] if kind == "application/ld+json" else None

    def handle_data(self, data: str) -> None:
        if self._buffer is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._buffer is not None:
            self.scripts.append("".join(self._buffer))
            self._buffer = None


def _job_postings(html_text: str) -> list[dict[str, Any]]:
    parser = _JsonLdParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # HTMLParser can raise on pathological markup; such a page has no usable JSON-LD
        return []
    postings: list[dict[str, Any]] = []
    for script in parser.scripts:
        try:
            data = json.loads(script.strip().removeprefix("<!--").removesuffix("-->"), strict=False)
        except ValueError:
            continue
        postings.extend(node for node in _json_ld_nodes(data) if _is_job_posting(node))
    return postings


_VOID_TAGS = frozenset({"meta", "link", "br", "img", "input", "hr", "source", "area", "base", "col", "wbr"})
_MAX_MICRODATA_DEPTH = 6


class _MicrodataParser(HTMLParser):
    """schema.org microdata items (``itemscope``/``itemprop``) as JSON-LD-shaped dicts.

    Nested items become nested dicts; ``meta`` values come from ``content``, links from
    ``href``, and other properties from their inner HTML (turned into text later).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, Any]] = []
        self._scopes: list[tuple[str, dict[str, Any], int]] = []  # (tag, item, depth)
        self._capture: tuple[str, str, int, dict[str, Any], list[str]] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: (value or "") for name, value in attrs}
        if self._capture is not None:
            self._capture[4].append(self.get_starttag_text() or "")
        if tag not in _VOID_TAGS:
            self._depth += 1
        prop = values.get("itemprop", "").strip()
        parent = self._scopes[-1][1] if self._scopes else None
        if "itemscope" in values and len(self._scopes) < _MAX_MICRODATA_DEPTH:
            item: dict[str, Any] = {"@type": values.get("itemtype", "").rstrip("/").rsplit("/", 1)[-1]}
            if prop and parent is not None:
                parent.setdefault(prop, item)
            elif not self._scopes:
                self.items.append(item)
            if tag not in _VOID_TAGS:
                self._scopes.append((tag, item, self._depth))
            return
        if not prop or parent is None or self._capture is not None:
            return
        if "content" in values:
            parent.setdefault(prop, values["content"])
        elif tag in {"a", "link"} and values.get("href"):
            parent.setdefault(prop, values["href"])
        elif tag not in _VOID_TAGS:
            self._capture = (tag, prop, self._depth, parent, [])

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture[4].append(html.escape(data))

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None:
            capture_tag, prop, depth, parent, parts = self._capture
            if tag == capture_tag and self._depth == depth:
                parent.setdefault(prop, "".join(parts))
                self._capture = None
            else:
                parts.append(f"</{tag}>")
        if self._scopes and self._scopes[-1][0] == tag and self._scopes[-1][2] == self._depth:
            self._scopes.pop()
        if tag not in _VOID_TAGS:
            self._depth = max(0, self._depth - 1)


def _microdata_postings(html_text: str) -> list[dict[str, Any]]:
    """``JobPosting`` items written as microdata (e.g. SAP SuccessFactors career sites)."""

    if "itemscope" not in html_text:
        return []
    parser = _MicrodataParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        return []
    postings = [item for item in parser.items if item.get("@type") == "JobPosting"]
    for posting in postings:
        title = posting.get("title")
        if isinstance(title, str):
            posting["title"] = html_to_text(title) or None
    return postings


def _json_ld_nodes(data: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth > 3:
        return
    if isinstance(data, list):
        for item in data[:200]:
            yield from _json_ld_nodes(item, depth + 1)
    elif isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            yield from _json_ld_nodes(graph, depth + 1)


def _is_job_posting(node: dict[str, Any]) -> bool:
    kinds = _as_list(node.get("@type"))
    return any(isinstance(kind, str) and kind.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1] == "JobPosting" for kind in kinds)


# -- field normalization ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Salary:
    fields: dict[str, Any]
    metadata: dict[str, Any]


def _salary(base: Any) -> _Salary | None:
    """Return a salary only when currency, a numeric amount and a period are all explicitly stated."""

    if not isinstance(base, dict):
        return None
    currency = base.get("currency")
    value = base.get("value")
    if not isinstance(value, dict):
        return None
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency.strip()):
        return None
    unit = value.get("unitText")
    period = _SALARY_PERIODS.get(unit.strip().upper()) if isinstance(unit, str) else None
    minimum, maximum, single = _amount(value.get("minValue")), _amount(value.get("maxValue")), _amount(value.get("value"))
    if period is None or not any(item is not None for item in (minimum, maximum, single)):
        return None
    low = minimum if minimum is not None else single if single is not None else maximum
    high = maximum if maximum is not None else single if single is not None else minimum
    if low is None or high is None or low > high:
        return None
    return _Salary(
        {"salary_min": low, "salary_max": high, "currency": currency.strip().upper(), "salary_period": period},
        {"salarySource": "jobposting_baseSalary"},
    )


def _amount(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,12}(\.[0-9]{1,2})?", text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _employment_type(value: Any) -> EmploymentType | None:
    mapped = {
        _EMPLOYMENT_TYPES.get(item.strip().upper())
        for item in _as_list(value)
        if isinstance(item, str) and item.strip()
    }
    # A posting that lists several different types is ambiguous; unknown stays unknown.
    return next(iter(mapped)) if len(mapped) == 1 and None not in mapped else None


def _location_text(value: Any) -> str | None:
    places: list[str] = []
    for place in _as_list(value)[:10]:
        if isinstance(place, str):
            text = _optional_text(place)
        elif isinstance(place, dict):
            address = place.get("address")
            if isinstance(address, dict):
                pieces = [
                    _optional_text(address.get("addressLocality")),
                    _optional_text(address.get("addressRegion")),
                    _country_name(address.get("addressCountry")),
                ]
                text = ", ".join(dict.fromkeys(piece for piece in pieces if piece)) or None
            else:
                text = _optional_text(address) or _optional_text(place.get("name"))
        else:
            text = None
        if text and text not in places:
            places.append(text)
    return "; ".join(places) or None


def _country_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _optional_text(value.get("name"))
    return _optional_text(value)


def _applicant_location_names(value: Any) -> list[str]:
    names = [_country_name(item) for item in _as_list(value)[:20] if isinstance(item, (dict, str))]
    return list(dict.fromkeys(name for name in names if name))


def _organization_name(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    text = _optional_text(value)
    return text if text is not None and len(text) <= 255 else None


def _identifier_value(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        return _optional_text(str(value))
    return None


def _parse_datetime(value: Any, now: datetime) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        try:  # SAP SuccessFactors microdata: "Tue Sep 29 00:00:00 UTC 2026"
            moment = datetime.strptime(value.strip(), "%a %b %d %H:%M:%S UTC %Y")
        except ValueError:
            return None
    moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment
    return moment if moment <= now + timedelta(days=1) else None  # a posting is not published in the future


def _is_expired(posting: dict[str, Any], now: datetime) -> bool:
    valid_through = _parse_datetime_any(posting.get("validThrough"))
    return valid_through is not None and valid_through < now


def _parse_datetime_any(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if len(value.strip()) <= 10:  # a date means the end of that day
        moment += timedelta(days=1)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _normalize_url(url: str) -> str:
    return urlsplit(url.strip())._replace(fragment="").geturl()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def _optional_text(value: Any) -> str | None:
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None
