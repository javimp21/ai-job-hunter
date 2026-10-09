"""New junior-level technical postings in the countries the owner wants to move to, announced on their own.

The normal alerts keep only what clears the priority bar. A junior posting abroad is rare, so each new one in the watched
countries (``tuning.junior_watch_countries``) is listed in one message whatever its priority, once per posting. Student
jobs and postings that demand fluent German or Dutch are left out (the candidate speaks neither). The postings already
announced are remembered in a small state file.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.candidates.exclusions import exclusion_reason
from ai_job_hunter.candidates.prefilter import title_may_be_relevant
from ai_job_hunter.models import HumanReviewStatus, Job, JobReview, JobSource
from ai_job_hunter.services.notifications import NotificationProvider, _safe_public_url

STATE_PATH = Path("data/local/junior-watch.json")
WINDOW_DAYS = 7
MAX_PER_MESSAGE = 15
_JUNIOR = ("junior", "graduate", "entry level", "entry-level", "associate", "trainee", "jr.")
_STUDENT = re.compile(r"working student|werkstudent|student|intern(ship)?\b|praktik|stage\b", re.IGNORECASE)
_LOCAL_LANGUAGE = re.compile(
    r"((fluent|proficient|native|excellent|good|strong|business).{0,25}(german|dutch|deutsch|nederlands)"
    r"|(german|dutch|deutsch|nederlands).{0,25}(fluent|required|mandatory|native|skills))",
    re.IGNORECASE,
)
# country -> pattern of the country and its main cities, as written in a posting's location
_PLACES = {
    "ireland": r"ireland|dublin|cork|galway|limerick",
    "netherlands": r"netherlands|nederland|amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|delft|enschede|groningen",
    "germany": r"germany|deutschland|berlin|munich|münchen|hamburg|frankfurt|cologne|köln|stuttgart|düsseldorf|leipzig|karlsruhe",
    "switzerland": r"switzerland|zurich|zürich|geneva|basel|lausanne|bern",
    "luxembourg": r"luxembourg",
    "belgium": r"belgium|brussels|antwerp|ghent|leuven",
    "sweden": r"sweden|stockholm|gothenburg|malmö",
    "denmark": r"denmark|copenhagen|aarhus",
    "finland": r"finland|helsinki|espoo|tampere",
    "norway": r"norway|oslo|bergen",
}


@dataclass(frozen=True, slots=True)
class Line:
    job_id: str
    title: str
    company: str
    location: str
    salary: str | None
    url: str | None


def _places_pattern(countries: list[str]) -> re.Pattern[str] | None:
    parts = [_PLACES.get(name.casefold(), re.escape(name.casefold())) for name in countries]
    return re.compile("|".join(parts), re.IGNORECASE) if parts else None


def _seen(path: Path) -> set[str]:
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _remember(path: Path, ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def _salary(source: JobSource) -> str | None:
    if source.salary_min is None or source.salary_period != "YEAR" or not source.salary_currency:
        return None
    high = f"–{int(source.salary_max) // 1000}k" if source.salary_max and source.salary_max != source.salary_min else ""
    return f"{int(source.salary_min) // 1000}k{high} {source.salary_currency}"


def collect(session: Session, candidate: CandidateConfig, *, now: datetime, state_path: Path = STATE_PATH) -> list[Line]:
    """The new postings to announce (nothing is remembered here)."""

    places = _places_pattern(candidate.tuning.junior_watch_countries)
    if places is None:
        return []
    since = now - timedelta(days=WINDOW_DAYS)
    seen = _seen(state_path)
    dismissed = set(session.scalars(select(JobReview.job_id).where(JobReview.state == HumanReviewStatus.DISMISSED.value)))
    sources = session.scalars(
        select(JobSource)
        .join(Job, Job.id == JobSource.job_id)
        .options(joinedload(JobSource.job).joinedload(Job.company))
        .where(
            JobSource.closed_at.is_(None),
            JobSource.discovered_at >= since,
            or_(*[Job.title.ilike(f"%{word}%") for word in _JUNIOR]),
        )
        .order_by(JobSource.discovered_at.desc())
    ).unique()
    sector = candidate.preferences.sector
    found: dict[str, Line] = {}
    for source in sources:
        job = source.job
        key = str(job.id)
        title = source.source_title or job.title
        place = source.source_location or job.location or ""
        if key in seen or key in found or job.id in dismissed or not places.search(place):
            continue
        if _STUDENT.search(title) or not title_may_be_relevant(title, sector):
            continue
        company = job.company.name if job.company else ""
        if exclusion_reason(title, company, candidate.preferences):
            continue
        if _LOCAL_LANGUAGE.search(source.source_description or job.description or ""):
            continue
        found[key] = Line(
            key, title, company, place, _salary(source),
            _safe_public_url(source.canonical_url or source.original_url or source.apply_url),
        )
    return list(found.values())


def format_message(lines: list[Line], countries: list[str]) -> str:
    head = f"🎓 Nivel junior nuevo en {', '.join(countries)}: {len(lines)}"
    body = []
    for line in lines[:MAX_PER_MESSAGE]:
        parts = [f"<b>{html.escape(line.title)}</b>", html.escape(line.company), html.escape(line.location[:40])]
        if line.salary:
            parts.append(line.salary)
        text = " · ".join(part for part in parts if part)
        body.append(f'• <a href="{html.escape(line.url, quote=True)}">{text}</a>' if line.url else f"• {text}")
    more = f"\n… y {len(lines) - MAX_PER_MESSAGE} más." if len(lines) > MAX_PER_MESSAGE else ""
    return head + "\n\n" + "\n".join(body) + more + "\n\nSin filtrar por prioridad; sin alemán ni neerlandés exigidos."


def send(
    session: Session, candidate: CandidateConfig, provider: NotificationProvider, *,
    now: datetime | None = None, state_path: Path = STATE_PATH,
) -> str:
    """"sent", "empty", "off" or "failed"; the announced postings are remembered only after Telegram accepted the message."""

    countries = candidate.tuning.junior_watch_countries
    if not countries:
        return "off"
    lines = collect(session, candidate, now=now or datetime.now(UTC), state_path=state_path)
    if not lines:
        return "empty"
    try:
        provider.send_message(format_message(lines, countries))
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing
        return "failed"
    _remember(state_path, _seen(state_path) | {line.job_id for line in lines})  # the ones past the cap are not repeated
    return "sent"
