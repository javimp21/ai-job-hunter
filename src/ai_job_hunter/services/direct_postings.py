"""Find the employer's own posting for jobs found on portals that charge candidates.

We Work Remotely and Remote OK ask candidates to pay before applying. The same
posting is usually on the employer's careers board, so before such a job alerts
we look for it there:

1. a job of the same company already in the database from another source with
   the same normalized title (company boards we monitor);
2. otherwise the company's public ATS board, guessed from its name, on the
   keyless JSON APIs the connectors already use (Greenhouse, Ashby, Workable,
   SmartRecruiters). Only a board that answers and lists a posting with the
   same normalized title counts; nothing is inferred.

Results (found or not) are cached in ``data/local/direct-postings.json`` so a
job is looked up at most once a day.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.connectors._portal_http import USER_AGENT
from ai_job_hunter.deduplication.normalization import normalize_company_name, normalize_job_title
from ai_job_hunter.models import Company, Job, JobSource

# Portals where applying needs a paid candidate plan: host suffix -> display name.
PAYWALLED_PORTALS = {"weworkremotely.com": "We Work Remotely", "remoteok.com": "Remote OK"}
PAYWALLED_PROVIDERS = frozenset({"weworkremotely", "remoteok"})
DEFAULT_STATE_PATH = Path("data/local/direct-postings.json")
RECHECK_AFTER = timedelta(hours=24)
_MAX_SLUGS = 2
_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class DirectPosting:
    url: str | None  # None: looked up, not found
    source: str | None  # "database" or "<ats>:<slug>"


def paywalled_portal(url: str | None) -> str | None:
    """Display name of the paywalled portal hosting ``url``, if any."""

    host = (urlsplit(url).hostname or "").lower() if url else ""
    for suffix, name in PAYWALLED_PORTALS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return None


def search_link(company: str, title: str) -> str:
    """A web search for the posting on the employer's site (fallback for the alert)."""

    query = httpx.QueryParams({"q": f'"{company}" "{title}" careers'})
    return f"https://duckduckgo.com/?{query}"


class DirectPostingResolver:
    """Cached lookup of the employer's posting for a paywalled job."""

    def __init__(
        self,
        session: Session,
        *,
        state_path: Path = DEFAULT_STATE_PATH,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        online: bool = True,
    ) -> None:
        self._session = session
        self._state_path = state_path
        self._client = client
        self._now = now
        self._online = online
        self._state: dict[str, Any] | None = None

    def __call__(self, job_id: UUID, company: str, title: str) -> DirectPosting | None:
        state = self._load()
        cached = state.get(str(job_id))
        if isinstance(cached, dict):
            found = DirectPosting(cached.get("url"), cached.get("source"))
            checked = _parse_time(cached.get("checked_at"))
            if found.url or not self._online or (checked and self._now() - checked < RECHECK_AFTER):
                return found
        elif not self._online:
            return None
        result = _from_database(self._session, job_id, company, title)
        if result is None and self._online:
            result = self._from_ats(company, title)
        result = result or DirectPosting(None, None)
        state[str(job_id)] = {"url": result.url, "source": result.source, "checked_at": self._now().isoformat()}
        self._save()
        return result

    def _from_ats(self, company: str, title: str) -> DirectPosting | None:
        client = self._client or httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT})
        try:
            for slug in company_slugs(company):
                for name, lookup in _ATS_LOOKUPS:
                    try:
                        url = lookup(client, slug, title)
                    except (httpx.HTTPError, ValueError):
                        url = None
                    if url:
                        return DirectPosting(url, f"{name}:{slug}")
        finally:
            if self._client is None:
                client.close()
        return None

    def _load(self) -> dict[str, Any]:
        if self._state is None:
            try:
                loaded = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = {}
            self._state = loaded if isinstance(loaded, dict) else {}
        return self._state

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(self._state, sort_keys=True), encoding="utf-8")
        except OSError:
            pass  # the cache is an optimisation; a lookup simply repeats


def company_slugs(company: str) -> list[str]:
    """Board identifiers to try: the normalized name joined, then hyphenated."""

    name = normalize_company_name(company) or company.casefold()
    words = re.findall(r"[a-z0-9]+", name)
    if not words:
        return []
    slugs = ["".join(words), "-".join(words)]
    return list(dict.fromkeys(slugs))[:_MAX_SLUGS]


def same_title(left: str, right: str) -> bool:
    a, b = normalize_job_title(left), normalize_job_title(right)
    return bool(a.tokens) and a.tokens == b.tokens and a.seniority == b.seniority


def _from_database(session: Session, job_id: UUID, company: str, title: str) -> DirectPosting | None:
    key = normalize_company_name(company) or company.casefold()
    words = re.findall(r"[a-z0-9]+", key)
    if not words:
        return None
    rows = session.execute(
        select(Job.title, Company.name, JobSource.apply_url, JobSource.canonical_url, JobSource.original_url)
        .join(Company, Company.id == Job.company_id)
        .join(JobSource, JobSource.job_id == Job.id)
        .where(
            Job.id != job_id,
            JobSource.provider.not_in(PAYWALLED_PROVIDERS),
            Company.name.ilike(f"%{max(words, key=len)}%"),  # narrows; the exact check is below
        )
    ).all()
    for other_title, other_company, apply_url, canonical_url, original_url in rows:
        if (normalize_company_name(other_company) or other_company.casefold()) != key:
            continue
        url = apply_url or canonical_url or original_url
        if url and not paywalled_portal(url) and same_title(title, other_title):
            return DirectPosting(url, "database")
    return None


def _get(client: httpx.Client, url: str) -> Any:
    response = client.get(url, timeout=_TIMEOUT)
    if response.status_code != 200:
        return None
    return response.json()


def _greenhouse(client: httpx.Client, slug: str, title: str) -> str | None:
    payload = _get(client, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    for job in (payload or {}).get("jobs") or []:
        if isinstance(job, dict) and same_title(title, str(job.get("title") or "")):
            return job.get("absolute_url") or None
    return None


def _ashby(client: httpx.Client, slug: str, title: str) -> str | None:
    payload = _get(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for job in (payload or {}).get("jobs") or []:
        if isinstance(job, dict) and same_title(title, str(job.get("title") or "")):
            return job.get("jobUrl") or None
    return None


def _workable(client: httpx.Client, slug: str, title: str) -> str | None:
    payload = _get(client, f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    for job in (payload or {}).get("jobs") or []:
        if isinstance(job, dict) and same_title(title, str(job.get("title") or "")):
            return job.get("url") or job.get("shortlink") or None
    return None


def _smartrecruiters(client: httpx.Client, slug: str, title: str) -> str | None:
    payload = _get(client, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings")
    for job in (payload or {}).get("content") or []:
        if isinstance(job, dict) and job.get("id") and same_title(title, str(job.get("name") or "")):
            return f"https://jobs.smartrecruiters.com/{slug}/{job['id']}"
    return None


_ATS_LOOKUPS: tuple[tuple[str, Callable[[httpx.Client, str, str], str | None]], ...] = (
    ("greenhouse", _greenhouse),
    ("ashby", _ashby),
    ("workable", _workable),
    ("smartrecruiters", _smartrecruiters),
)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=UTC)
