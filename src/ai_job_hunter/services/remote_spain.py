"""A weekly list of remote offers that say they are open to Spain, whatever level they ask for.

The normal alerts keep only what fits the candidate's level today. This list is for watching a goal further away (for
example remote jobs for companies abroad): every open remote offer whose posting says it accepts Spain (or anywhere),
in the candidate's role family, newest week first, with the years it asks for and the salary when it is published.
Nothing here evaluates anything; it only reads what is stored.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.candidates.exclusions import exclusion_reason
from ai_job_hunter.candidates.prefilter import title_may_be_relevant
from ai_job_hunter.models import HumanReviewStatus, Job, JobReview, JobSource, ReportDelivery
from ai_job_hunter.services.notifications import NotificationProvider, _safe_public_url

KIND = "REMOTE_SPAIN"
MIN_INTERVAL = timedelta(days=6)
OPEN_TO_SPAIN = ("WORLDWIDE", "SPAIN_ONLY")
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|años)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Line:
    title: str
    company: str
    url: str | None
    years: int | None
    salary: str | None
    worldwide: bool


def _years_asked(text: str) -> int | None:
    found = [int(value) for value in _YEARS.findall(text or "") if 0 < int(value) <= 20]
    return found[0] if found else None


def _salary(source: JobSource) -> str | None:
    if source.salary_min is None or source.salary_period != "YEAR" or not source.salary_currency:
        return None
    low = f"{int(source.salary_min) // 1000}k"
    high = f"–{int(source.salary_max) // 1000}k" if source.salary_max and source.salary_max != source.salary_min else ""
    return f"{low}{high} {source.salary_currency}"


def collect(session: Session, candidate: CandidateConfig, *, now: datetime, days: int = 7, limit: int = 15) -> list[Line]:
    since = now - timedelta(days=days)
    sources = session.scalars(
        select(JobSource)
        .options(joinedload(JobSource.job).joinedload(Job.company))
        .where(
            JobSource.closed_at.is_(None),
            JobSource.remote_policy == "REMOTE",
            JobSource.remote_eligibility.in_(OPEN_TO_SPAIN),
            JobSource.discovered_at >= since,
        )
        .order_by(JobSource.discovered_at.desc())
    ).unique()
    dismissed = set(
        session.scalars(select(JobReview.job_id).where(JobReview.state == HumanReviewStatus.DISMISSED.value))
    )
    seen: set = set()
    rows: list[tuple[Line, int]] = []
    sector = candidate.preferences.sector
    for source in sources:
        job = source.job
        if job.id in seen or job.id in dismissed:
            continue
        title = source.source_title or job.title
        company = job.company.name if job.company else ""
        if not title_may_be_relevant(title, sector) or exclusion_reason(title, company, candidate.preferences):
            continue
        seen.add(job.id)
        line = Line(
            title=title, company=company, url=_safe_public_url(source.apply_url or source.canonical_url or source.original_url),
            years=_years_asked(source.source_description or job.description or ""), salary=_salary(source),
            worldwide=source.remote_eligibility == "WORLDWIDE",
        )
        rows.append((line, int(source.salary_max or source.salary_min or 0)))
    rows.sort(key=lambda row: -row[1])
    return [line for line, _ in rows[:limit]]


def format_message(lines: list[Line], total_seen_days: int = 7) -> str:
    head = f"🌍 Remotas abiertas a España (nuevas en {total_seen_days} días): {len(lines)}"
    body = []
    for line in lines:
        parts = [f"<b>{html.escape(line.title)}</b>", html.escape(line.company)]
        if line.salary:
            parts.append(line.salary)
        parts.append(f"pide {line.years} años" if line.years else "años no indicados")
        parts.append("cualquier país" if line.worldwide else "solo España")
        text = " · ".join(parts)
        body.append(f'• <a href="{html.escape(line.url, quote=True)}">{text}</a>' if line.url else f"• {text}")
    return head + "\n\n" + "\n".join(body) + "\n\nSon ofertas que dicen aceptar España, sin filtrar por tu nivel: sirven para ver qué piden y cuánto pagan."


def send(
    session: Session, candidate: CandidateConfig, provider: NotificationProvider, *,
    now: datetime | None = None, force: bool = False,
) -> str:
    """"sent", "too_soon", "empty" or "failed"; the marker is written only after delivery."""

    moment = now or datetime.now(UTC)
    if not force:
        last = session.scalar(select(func.max(ReportDelivery.sent_at)).where(ReportDelivery.kind == KIND))
        if last is not None and moment - (last if last.tzinfo else last.replace(tzinfo=UTC)) < MIN_INTERVAL:
            return "too_soon"
    lines = collect(session, candidate, now=moment)
    if not lines:
        return "empty"
    try:
        sent = provider.send_message(format_message(lines))
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing
        session.rollback()
        return "failed"
    session.add(ReportDelivery(kind=KIND, period_start=moment, period_end=moment, provider_message_id=sent.message_id, sent_at=moment))
    session.commit()
    return "sent"
