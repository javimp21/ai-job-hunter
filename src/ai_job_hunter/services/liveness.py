"""Is a posting still open? A cheap check before an alert is sent.

Aggregator postings (LinkedIn through TheirStack, Adzuna, remote portals) can stay in a feed after the
employer closed the role. Just before an alert is sent, the posting page is read once: a 404/410 or
closing wording ("no longer accepting applications") means closed. Anything else, including a blocked
or failing request, is unknown and the alert goes out as before. Only public https pages are read,
with a short timeout and few redirects, and company boards (ATS) are not checked here because their
own refresh already closes vanished postings.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

import httpx

from ai_job_hunter.company_leads import CareerPageDiscoveryError, _resolve_host, _validate_public_url

# Hosts whose postings can outlive the vacancy.
AGGREGATOR_HOSTS = (
    "linkedin.com", "adzuna.es", "adzuna.nl", "adzuna.ch", "himalayas.app", "manfred.com", "remotive.com",
    "jobicy.com", "arbeitnow.com", "4dayweek.io", "weworkremotely.com", "remoteok.com", "remoteok.io",
)
MAX_BYTES = 400_000
USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"

# Written in the normalized alphabet: ASCII quotes, no accents, lower case, collapsed spaces.
_CLOSED = re.compile(
    r"no longer accepting applications|(?:job|position|role|posting|vacancy)(?: is| has)? no longer (?:available|open)"
    r"|this (?:job|position|role|posting) (?:has expired|is closed(?![- ]loop))"
    r"|(?:job|position|role|posting|vacancy)[^.]{0,60}has been filled"
    r"|oferta (?:ya )?no (?:esta|se encuentra) disponible|ya no (?:acepta|aceptamos) (?:solicitudes|candidaturas)"
    r"|esta oferta (?:ha caducado|esta cerrada|ha sido cerrada)"
    r"|vacature is (?:niet meer|reeds) beschikbaar|deze vacature is gesloten"
    r"|diese stelle ist (?:nicht mehr|bereits) (?:verfugbar|besetzt)|stellenanzeige (?:ist )?abgelaufen"
)
_SCRIPTS = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")

LivenessCheck = Callable[[str], bool | None]
"""Returns False when the posting is closed, True when it is open and None when unknown."""


def needs_check(url: str | None) -> bool:
    host = (urlsplit(url).hostname or "").lower() if url else ""
    return any(host == suffix or host.endswith("." + suffix) for suffix in AGGREGATOR_HOSTS)


def _normalize(text: str) -> str:
    text = _TAGS.sub(" ", _SCRIPTS.sub(" ", text))
    text = text.replace("’", "'").replace("‘", "'")
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded)


def page_says_closed(html: str) -> bool:
    return bool(_CLOSED.search(_normalize(html)))


class PostingLiveness:
    """Callable check with a per-run memory so the same URL is never read twice."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 10.0,
        resolver: Callable[[str, int], Iterable[str]] = _resolve_host,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._timeout = timeout
        self._seen: dict[str, bool | None] = {}

    def __call__(self, url: str) -> bool | None:
        if not needs_check(url):
            return None
        if url not in self._seen:
            self._seen[url] = self._check(url)
        return self._seen[url]

    def _check(self, url: str) -> bool | None:
        client = self._client or httpx.Client(follow_redirects=False, headers={"User-Agent": USER_AGENT})
        try:
            current = url
            for _hop in range(4):
                try:
                    _validate_public_url(current, self._resolver)
                    response = client.get(current, timeout=self._timeout)
                except (CareerPageDiscoveryError, httpx.HTTPError):
                    return None
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code in {404, 410}:
                    return False
                if response.status_code != 200:
                    return None
                return False if page_says_closed(response.text[:MAX_BYTES]) else True
            return None
        finally:
            if self._client is None:
                client.close()
