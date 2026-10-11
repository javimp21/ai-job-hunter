"""New junior-level and QA postings the owner wants to hear about, announced on their own.

The normal alerts keep only what clears the priority bar. Two kinds of posting are rare enough to list in one message
whatever their priority, once per posting:

* junior-level technical postings in the countries of ``tuning.junior_watch_countries`` (only Java, software, backend and
  full stack developer or engineer titles count);
* QA / test automation postings (any level but senior, asking for fewer than four years) in the countries of
  ``tuning.qa_watch_countries``.

Student jobs and postings that demand fluent German or Dutch are left out (the candidate speaks neither). The postings
already announced are remembered in a small state file.
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
_QA_WORDS = ("qa", "quality", "test", "sdet", "automation")
_STUDENT = re.compile(r"working student|werkstudent|student|intern(ship)?\b|praktik|stage\b", re.IGNORECASE)
# Only the roles the owner wants for the junior watch: Java, software, backend or full stack developer/engineer.
_ROLE = re.compile(r"(java|software|back-?end|back end|full[ -]?stack).{0,30}(developer|engineer|engineering)", re.IGNORECASE)
# Software QA only: not data raters, hardware or field testing, and not "automation engineer" in general.
_QA_ROLE = re.compile(
    r"\bqa\b.{0,30}(engineer|analyst|tester|developer|automation)|(engineer|analyst|tester|developer).{0,15}\bqa\b"
    r"|quality assurance (engineer|analyst|tester)|test automation|automation test|\bsdet\b|engineer in test"
    r"|software (test|testing|quality) (engineer|analyst)",
    re.IGNORECASE,
)
_NOT_SOFTWARE_QA = re.compile(
    r"rater|labell?ing|annotation|flight|environmental|hardware|mechanical|electrical|vehicle|aircraft|energy|manufactur"
    r"|production test|field test|system test|drug|clinical|laboratory|chemical|food|\bhvac\b",
    re.IGNORECASE,
)
_SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head|manager|director|architect)\b|\b(ii|iii|iv)\b", re.IGNORECASE)
_MANY_YEARS = re.compile(r"(\b[4-9]|1[0-9])\+? ?(years|jahre|años)", re.IGNORECASE)
_LOCAL_LANGUAGE = re.compile(
    r"((fluent|proficient|native|excellent|good|strong|business).{0,25}(german|dutch|deutsch|nederlands)"
    r"|(german|dutch|deutsch|nederlands).{0,25}(fluent|required|mandatory|native|skills))",
    re.IGNORECASE,
)
# country -> pattern of the country and its main cities, as written in a posting's location
_PLACES = {
    "spain": r"spain|españa|madrid|barcelona|valencia|sevilla|málaga|malaga|bilbao|zaragoza|coruña|vigo|oviedo|murcia",
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
    kind: str  # "junior" or "qa"
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

    junior_places = _places_pattern(candidate.tuning.junior_watch_countries)
    qa_places = _places_pattern(candidate.tuning.qa_watch_countries)
    if junior_places is None and qa_places is None:
        return []
    since = now - timedelta(days=WINDOW_DAYS)
    seen = _seen(state_path)
    dismissed = set(session.scalars(select(JobReview.job_id).where(JobReview.state == HumanReviewStatus.DISMISSED.value)))
    words = [*(_JUNIOR if junior_places else ()), *(_QA_WORDS if qa_places else ())]
    sources = session.scalars(
        select(JobSource)
        .join(Job, Job.id == JobSource.job_id)
        .options(joinedload(JobSource.job).joinedload(Job.company))
        .where(
            JobSource.closed_at.is_(None),
            JobSource.discovered_at >= since,
            or_(*[Job.title.ilike(f"%{word}%") for word in words]),
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
        if key in seen or key in found or job.id in dismissed or _STUDENT.search(title):
            continue
        company = job.company.name if job.company else ""
        if exclusion_reason(title, company, candidate.preferences):
            continue
        text = source.source_description or job.description or ""
        kind = None
        if (
            junior_places and junior_places.search(place) and any(word in title.casefold() for word in _JUNIOR)
            and _ROLE.search(title) and title_may_be_relevant(title, sector) and not _LOCAL_LANGUAGE.search(text)
        ):
            kind = "junior"
        elif (
            qa_places and qa_places.search(place) and _QA_ROLE.search(title) and not _NOT_SOFTWARE_QA.search(title)
            and not _SENIOR.search(title)
            and not _MANY_YEARS.search(text) and not _LOCAL_LANGUAGE.search(text)
        ):
            kind = "qa"
        if kind is None:
            continue
        found[key] = Line(
            kind, key, title, company, place, _salary(source),
            _safe_public_url(source.canonical_url or source.original_url or source.apply_url),
        )
    return list(found.values())


def _block(head: str, lines: list[Line], more: int = 0) -> str:
    body = []
    for line in lines:
        parts = [f"<b>{html.escape(line.title)}</b>", html.escape(line.company), html.escape(line.location[:40])]
        if line.salary:
            parts.append(line.salary)
        text = " · ".join(part for part in parts if part)
        body.append(f'• <a href="{html.escape(line.url, quote=True)}">{text}</a>' if line.url else f"• {text}")
    rest = f"\n… y {more} más: te llegan en los próximos minutos." if more else ""
    return head + "\n\n" + "\n".join(body) + rest


def select_for_message(lines: list[Line]) -> list[Line]:
    """At most ``MAX_PER_MESSAGE`` of each kind; the rest stay unannounced and come in the next run."""

    return [line for kind in ("junior", "qa") for line in [item for item in lines if item.kind == kind][:MAX_PER_MESSAGE]]


def format_message(lines: list[Line], countries: list[str], pending: list[Line] | None = None) -> str:
    """The message for ``lines`` (already limited); ``pending`` are the ones still to come, counted per kind."""

    waiting = pending or []
    juniors = [line for line in lines if line.kind == "junior"]
    qa = [line for line in lines if line.kind == "qa"]
    parts = []
    if juniors:
        more = sum(1 for line in waiting if line.kind == "junior")
        parts.append(_block(f"🎓 Nivel junior nuevo en {', '.join(countries)}: {len(juniors) + more}", juniors, more))
    if qa:
        more = sum(1 for line in waiting if line.kind == "qa")
        parts.append(_block(f"🧪 QA / automatización de pruebas nuevo: {len(qa) + more}", qa, more))
    return "\n\n".join(parts) + "\n\nSin filtrar por prioridad; sin alemán ni neerlandés exigidos."


def send(
    session: Session, candidate: CandidateConfig, provider: NotificationProvider, *,
    now: datetime | None = None, state_path: Path = STATE_PATH,
) -> str:
    """"sent", "empty", "off" or "failed"; the announced postings are remembered only after Telegram accepted the message."""

    countries = candidate.tuning.junior_watch_countries
    if not countries and not candidate.tuning.qa_watch_countries:
        return "off"
    lines = collect(session, candidate, now=now or datetime.now(UTC), state_path=state_path)
    if not lines:
        return "empty"
    shown = select_for_message(lines)
    waiting = [line for line in lines if line not in shown]
    try:
        provider.send_message(format_message(shown, countries, waiting))
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing
        return "failed"
    _remember(state_path, _seen(state_path) | {line.job_id for line in shown})  # the rest are announced in the next run
    return "sent"
