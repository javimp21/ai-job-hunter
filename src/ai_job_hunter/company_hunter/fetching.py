"""Polite, bounded fetching of a company's own public pages.

Rules enforced here, not left to callers: robots.txt is respected for every
request (including redirect hops), requests to one host are spaced out, the
number of pages per run and the size of each page are capped, only public
http(s) hosts are fetched, and linkedin.com is never fetched at all.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ai_job_hunter.company_leads import _resolve_host, _validate_public_url, CareerPageDiscoveryError

HUNTER_USER_AGENT = "AI-Job-Hunter/0.1 (personal job search; reads public team pages politely)"
ROBOTS_PRODUCT_TOKEN = "AI-Job-Hunter"
MAX_PAGE_BYTES = 3_000_000
MAX_REDIRECTS = 3
DEFAULT_MIN_DELAY_SECONDS = 1.5
MAX_CRAWL_DELAY_SECONDS = 10.0
_BLOCKED_HOST_SUFFIXES = ("linkedin.com",)


class FetchRefused(RuntimeError):
    """A page was not fetched on purpose or could not be fetched; the message is safe to show."""


@dataclass(slots=True)
class _Robots:
    parser: RobotFileParser | None  # None means "allow everything"
    disallow_all: bool = False
    delay: float = 0.0


@dataclass
class PoliteFetcher:
    client: httpx.Client | None = None
    user_agent: str = HUNTER_USER_AGENT
    min_delay: float = DEFAULT_MIN_DELAY_SECONDS
    max_pages: int = 8
    max_api_calls: int = 7
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    host_resolver: Callable[[str, int], Iterable[str]] = _resolve_host
    pages_fetched: int = 0
    fetched: list[str] = field(default_factory=list)  # final URLs, for the run report
    api_calls: int = 0
    _robots: dict[str, _Robots] = field(default_factory=dict)
    _last_request: dict[str, float] = field(default_factory=dict)

    # -- public API ------------------------------------------------------------------

    def get_html(self, url: str) -> tuple[str, str]:
        """Return (final_url, html) or raise FetchRefused."""

        if self.pages_fetched >= self.max_pages:
            raise FetchRefused("page budget for this company is used up")
        final_url, body = self._get(url, accept="text/html,application/xhtml+xml;q=0.9", kind="html")
        self.pages_fetched += 1
        self.fetched.append(final_url)
        return final_url, body

    def get_public_json(self, url: str, *, allowed_hosts: frozenset[str]) -> object:
        """Fetch JSON from an explicitly allowed public API host (counts against the budget)."""

        host = (urlsplit(url).hostname or "").casefold()
        if host not in allowed_hosts:
            raise FetchRefused("API host is not allowed")
        if self.api_calls >= self.max_api_calls:
            raise FetchRefused("API call budget for this company is used up")
        _, body = self._get(url, accept="application/vnd.github+json, application/json", kind="json", robots=False)
        self.api_calls += 1
        try:
            return json.loads(body)
        except ValueError:
            raise FetchRefused("API response was not JSON") from None

    # -- internals -------------------------------------------------------------------

    def _get(self, url: str, *, accept: str, kind: str, robots: bool = True) -> tuple[str, str]:
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            self._check_target(current)
            if robots:
                self._check_robots(current)
            response_url, status, location, text = self._request(current, accept, kind)
            if status in {301, 302, 303, 307, 308}:
                if not location or hop >= MAX_REDIRECTS:
                    raise FetchRefused("redirect could not be followed")
                current = urljoin(current, location)
                continue
            if status != 200:
                raise FetchRefused(f"HTTP {status}")
            return response_url, text
        raise FetchRefused("too many redirects")

    def _check_target(self, url: str) -> None:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        if any(host == suffix or host.endswith("." + suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
            raise FetchRefused("linkedin.com is never fetched")
        try:
            _validate_public_url(url, self.host_resolver)
        except CareerPageDiscoveryError as error:
            raise FetchRefused(str(error)) from None

    def _request(self, url: str, accept: str, kind: str) -> tuple[str, int, str | None, str]:
        host = (urlsplit(url).hostname or "").casefold()
        self._wait(host, self._robots.get(self._origin(url)))
        client = self.client or httpx.Client()
        try:
            with client.stream(
                "GET",
                url,
                follow_redirects=False,
                headers={"Accept": accept, "User-Agent": self.user_agent},
                timeout=15.0,
            ) as response:
                self._last_request[host] = self.clock()
                if response.status_code in {301, 302, 303, 307, 308}:
                    return url, response.status_code, response.headers.get("location"), ""
                if response.status_code != 200:
                    return url, response.status_code, None, ""
                content_type = response.headers.get("content-type", "").casefold()
                if kind == "html" and content_type and "html" not in content_type:
                    raise FetchRefused("response was not HTML")
                size = 0
                chunks: list[bytes] = []
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise FetchRefused("response exceeded the size limit")
                    chunks.append(chunk)
                text = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                return str(response.url), 200, None, text
        except httpx.HTTPError as error:
            raise FetchRefused(f"request failed ({type(error).__name__})") from None
        finally:
            if self.client is None:
                client.close()

    def _wait(self, host: str, robots: _Robots | None) -> None:
        delay = max(self.min_delay, robots.delay if robots else 0.0)
        last = self._last_request.get(host)
        if last is not None:
            remaining = delay - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme.casefold()}://{(parts.netloc or '').casefold()}"

    def _check_robots(self, url: str) -> None:
        origin = self._origin(url)
        robots = self._robots.get(origin)
        if robots is None:
            robots = self._load_robots(origin)
            self._robots[origin] = robots
        if robots.disallow_all:
            raise FetchRefused("robots.txt unavailable (5xx); not fetching")
        if robots.parser is not None and not robots.parser.can_fetch(ROBOTS_PRODUCT_TOKEN, url):
            raise FetchRefused("blocked by robots.txt")

    def _load_robots(self, origin: str) -> _Robots:
        robots_url = origin + "/robots.txt"
        self._check_target(robots_url)
        self._wait(urlsplit(robots_url).hostname or "", None)
        client = self.client or httpx.Client()
        try:
            response = client.get(
                robots_url,
                follow_redirects=False,
                headers={"User-Agent": self.user_agent, "Accept": "text/plain"},
                timeout=10.0,
            )
            self._last_request[(urlsplit(robots_url).hostname or "").casefold()] = self.clock()
        except httpx.HTTPError:
            # RFC 9309: an unreachable robots.txt means do not crawl.
            return _Robots(parser=None, disallow_all=True)
        finally:
            if self.client is None:
                client.close()
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            # Unreachable (5xx) or relocated robots.txt: be conservative and do not crawl.
            return _Robots(parser=None, disallow_all=True)
        if response.status_code != 200:
            # 4xx (including 404): no robots file, everything is allowed.
            return _Robots(parser=None)
        parser = RobotFileParser()
        parser.parse(response.text[:500_000].splitlines())
        delay = parser.crawl_delay(ROBOTS_PRODUCT_TOKEN) or parser.crawl_delay("*") or 0
        return _Robots(parser=parser, delay=min(float(delay), MAX_CRAWL_DELAY_SECONDS))
