"""Company leads from Hacker News "Ask HN: Who is hiring?" monthly threads.

A thread is only a discovery signal: each top-level comment names a company,
its links and a header line ("Company | Role | Location | REMOTE ..."). Jobs
are still verified later on the official careers page / ATS. Data comes from
the public HN Algolia API (two requests per import).
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ai_job_hunter.ats_discovery import discover_ats_url
from ai_job_hunter.company_leads import CompanyLeadInput, CompanyLeadsConfig, CompanyLeadsConfigError
from ai_job_hunter.domain.company_intelligence import ATSProvider

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
_REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)
_REACHABLE_REGION = re.compile(
    r"\b(?:eu|europe|european|emea|global|globally|worldwide|anywhere|spain|madrid|cet|cest)\b", re.IGNORECASE
)
_HREF = re.compile(r'href="([^"]+)"')
_TRACKING_PREFIXES = ("utm_",)
_SKIP_HOSTS = ("news.ycombinator.com", "ycombinator.com", "linkedin.com", "twitter.com", "x.com")
# Hosts that are never the company's own website (ATS, job boards, chats, schedulers).
_NOT_COMPANY_SITES = (
    "ashbyhq.com", "greenhouse.io", "lever.co", "dover.com", "workable.com", "teamtailor.com",
    "smartrecruiters.com", "personio.de", "recruitee.com", "wellfound.com", "ycombinator.com",
    "zulipchat.com", "discord.gg", "discord.com", "slack.com", "calendly.com", "forms.gle", "google.com",
)
_CHAT_HOSTS = ("zulipchat.com", "discord.gg", "discord.com", "slack.com", "calendly.com", "forms.gle")


class HNHiringError(RuntimeError):
    """A safe, user-readable failure fetching or parsing the thread."""


def fetch_latest_thread(
    client: httpx.Client | None = None, *, needs_import: Callable[[str, datetime | None], bool] | None = None
) -> Mapping[str, Any] | None:
    """Return the newest "Ask HN: Who is hiring?" thread with its comments.

    With ``needs_import`` the thread body is only downloaded when that callback
    (thread id, posting time) says so; otherwise ``None`` is returned after a
    single search request.
    """

    owns = client is None
    active = client or httpx.Client(timeout=30.0, headers={"User-Agent": "AI-Job-Hunter/0.1"})
    try:
        search = _get_json(
            active, SEARCH_URL, {"tags": "story,author_whoishiring", "query": "Who is hiring", "hitsPerPage": 5}
        )
        hits = [hit for hit in search.get("hits") or [] if str(hit.get("title", "")).startswith("Ask HN: Who is hiring?")]
        if not hits:
            raise HNHiringError("No 'Who is hiring?' thread was found.")
        newest = hits[0]
        if needs_import is not None and not needs_import(str(newest["objectID"]), _posted_at(newest)):
            return None
        return _get_json(active, ITEM_URL.format(id=newest["objectID"]), None)
    finally:
        if owns:
            active.close()


def _posted_at(item: Mapping[str, Any]) -> datetime | None:
    stamp = item.get("created_at_i")
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        return None
    return datetime.fromtimestamp(stamp, UTC)


def leads_from_thread(thread: Mapping[str, Any], *, reachable_only: bool = True) -> CompanyLeadsConfig:
    """Turn top-level job comments into company leads.

    With ``reachable_only`` (default) only comments that say REMOTE together
    with Europe/EU/EMEA/global/worldwide/anywhere/Spain/CET are kept.
    """

    title = str(thread.get("title") or "Ask HN: Who is hiring?")
    leads: list[CompanyLeadInput] = []
    seen: set[str] = set()
    for comment in thread.get("children") or []:
        raw = comment.get("text") if isinstance(comment, Mapping) else None
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = _plain_text(raw)
        header = text.strip().split("\n", 1)[0].strip()
        if reachable_only and not (_REMOTE.search(text) and _REACHABLE_REGION.search(text)):
            continue
        company = _company_name(header)
        if not company or company.casefold() in seen:
            continue
        links = [_clean_url(html.unescape(link)) for link in _HREF.findall(raw)]
        links = [link for link in links if link and not _host(link).endswith(_SKIP_HOSTS)]
        careers = next((link for link in links if _is_ats(link)), None) or next(
            (link for link in links if _looks_like_careers(link) and not _host(link).endswith(_CHAT_HOSTS)), None
        )
        website = next(
            (link for link in links if link != careers and not _host(link).endswith(_NOT_COMPANY_SITES)), None
        )
        if website:
            parts = urlsplit(website)
            website = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        comment_url = f"https://news.ycombinator.com/item?id={comment.get('id')}"
        try:
            leads.append(
                CompanyLeadInput(
                    company_name=company[:255],
                    website_url=website,
                    careers_url=careers,
                    source_type="hn_who_is_hiring",
                    source_label=title[:255],
                    source_url=comment_url,
                    hiring_hint=header[:512],
                    notes="Discovery signal only; verify roles on the official careers page/ATS.",
                )
            )
        except ValueError:
            continue
        seen.add(company.casefold())
    if not leads:
        raise CompanyLeadsConfigError("The thread contained no matching company postings.")
    return CompanyLeadsConfig(leads=leads)


def _get_json(client: httpx.Client, url: str, params: dict[str, Any] | None) -> Mapping[str, Any]:
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as error:
        raise HNHiringError(f"Hacker News request failed ({type(error).__name__}).") from None
    if response.status_code != 200:
        raise HNHiringError(f"Hacker News API returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError:
        raise HNHiringError("Hacker News API returned invalid JSON.") from None
    if not isinstance(payload, Mapping):
        raise HNHiringError("Hacker News API returned an unexpected payload.")
    return payload


def _plain_text(raw: str) -> str:
    text = re.sub(r"<p>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def _company_name(header: str) -> str | None:
    first = header.split("|", 1)[0]
    first = re.sub(r"\(.*?\)|https?://\S+", " ", first)
    name = " ".join(first.split()).strip(" -–—:,")
    label = re.match(r"^(company|employer)\s*:\s*", name, re.IGNORECASE)
    if label:
        name = name[label.end():]
    elif re.match(r"^(location|role|position|remote|salary|compensation|title)\s*:", name, re.IGNORECASE):
        return None  # a field label, not a company name
    return name or None


def _clean_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if not key.startswith(_TRACKING_PREFIXES)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold()


def _is_ats(url: str) -> bool:
    return discover_ats_url(url).provider is not ATSProvider.UNKNOWN


def _looks_like_careers(url: str) -> bool:
    return bool(re.search(r"/(?:careers?|jobs?|join(?:-us)?|work-with-us|hiring)\b", urlsplit(url).path, re.IGNORECASE))
