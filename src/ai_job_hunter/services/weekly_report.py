"""Weekly Telegram report: what the hunter found and how the candidate reacted.

Every number comes from persisted rows (jobs, evaluations, the notification
ledger, human reviews, monitored sources). Nothing is estimated: when a figure
cannot be computed (e.g. no published EUR salary) the section says so, and the
suggestions are plain rules over those same figures.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates import CandidateConfig, PreFilterDecision
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import (
    HumanReviewStatus,
    Job,
    JobReview,
    JobSource,
    OpportunityNotification,
    ReportDelivery,
)
from ai_job_hunter.services.digest import DIGEST_CHANNEL, _aware, _failing_sources
from ai_job_hunter.services.notifications import (
    TELEGRAM_CHANNEL,
    NotificationProvider,
    _html,
)
from ai_job_hunter.services.opportunities import Opportunity, list_opportunities

WEEKLY_KIND = "WEEKLY"
REPORT_DAYS = 7
# A weekly timer can drift by a few hours; 6 days still means "once a week".
WEEKLY_MIN_INTERVAL = timedelta(days=6)
TOP_N = 5
TECH_TOP_N = 8
# Suggestion thresholds: a pattern needs enough jobs/reviews to be worth saying.
MIN_TECH_JOBS = 3
MIN_TECH_SHARE = 0.25
MIN_REASON_COUNT = 3
MIN_REASON_SHARE = 0.4

_YEARLY_FACTOR = {"YEAR": Decimal(1), "MONTH": Decimal(12)}
_REASON_LABELS = {
    "salary": "salario",
    "location": "ubicación",
    "role": "rol",
    "seniority": "seniority",
    "experience": "experiencia",
    "stack": "stack",
    "company": "empresa",
    "not_interesting": "no me interesa",
    "learning": "aprender",
    "product": "producto",
    "remote": "remoto",
    "career": "carrera",
    "other": "otro",
}
_NO_REASON = "sin motivo"


@dataclass(frozen=True, slots=True)
class SalaryStats:
    """Published EUR salaries, yearly. ``count`` of ``relevant`` jobs carry one."""

    count: int
    relevant: int
    median: Decimal
    minimum: Decimal
    maximum: Decimal


@dataclass(frozen=True, slots=True)
class TechCount:
    name: str
    jobs: int
    in_stack: bool


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    period_start: datetime
    period_end: datetime
    discovered: int
    passed_prefilter: int
    evaluated: int
    apply: int
    review: int
    alerts_sent: int
    digest_items: int
    top_companies: tuple[tuple[str, int], ...]
    top_sources: tuple[tuple[str, int], ...]
    technologies: tuple[TechCount, ...]
    technologies_saved: tuple[TechCount, ...]
    technologies_dismissed: tuple[TechCount, ...]
    salary: SalaryStats | None
    thumbs_up: int
    thumbs_down: int
    reasons_up: tuple[tuple[str, int], ...]
    reasons_down: tuple[tuple[str, int], ...]
    failing_sources: tuple[str, ...]
    suggestions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeeklyResult:
    status: str  # "sent", "preview", "too_soon", "failed"
    report: WeeklyReport | None = None
    message: str | None = None


def build_weekly_report(
    session: Session,
    candidate: CandidateConfig,
    *,
    now: datetime | None = None,
    days: int = REPORT_DAYS,
) -> WeeklyReport:
    end = _aware(now or datetime.now(UTC))
    start = end - timedelta(days=days)
    items = list_opportunities(
        session,
        candidate,
        limit=100_000,
        include_applied=True,
        include_skip=True,
        include_dismissed=True,
        include_closed=True,
    )
    by_id = {item.job_id: item for item in items}
    new_items = [
        item for item in items if item.first_seen_at is not None and start <= _aware(item.first_seen_at) <= end
    ]
    relevant = [item for item in new_items if _is_relevant(item)]
    stack = _candidate_stack(candidate)

    reviews = session.scalars(
        select(JobReview).where(
            JobReview.state.in_((HumanReviewStatus.SAVED.value, HumanReviewStatus.DISMISSED.value)),
            JobReview.updated_at >= start,
            JobReview.updated_at <= end,
        )
    ).all()
    saved = [row for row in reviews if row.state == HumanReviewStatus.SAVED.value]
    dismissed = [row for row in reviews if row.state == HumanReviewStatus.DISMISSED.value]

    report = WeeklyReport(
        period_start=start,
        period_end=end,
        discovered=_discovered_count(session, start, end),
        passed_prefilter=sum(1 for item in new_items if _passed_prefilter(item)),
        evaluated=sum(1 for item in new_items if _passed_prefilter(item) and item.decision is not None),
        apply=sum(1 for item in new_items if item.decision is FinalDecision.APPLY),
        review=sum(1 for item in new_items if item.decision is FinalDecision.REVIEW),
        alerts_sent=_sent_count(session, TELEGRAM_CHANNEL, start, end),
        digest_items=_sent_count(session, DIGEST_CHANNEL, start, end),
        top_companies=tuple(Counter(item.company for item in relevant).most_common(TOP_N)),
        top_sources=_top_sources(session, relevant),
        technologies=_tech_counts(relevant, stack, TECH_TOP_N),
        technologies_saved=_tech_counts(_items_of(saved, by_id), stack, TOP_N),
        technologies_dismissed=_tech_counts(_items_of(dismissed, by_id), stack, TOP_N),
        salary=_salary_stats(relevant),
        thumbs_up=len(saved),
        thumbs_down=len(dismissed),
        reasons_up=_reason_counts(saved),
        reasons_down=_reason_counts(dismissed),
        failing_sources=tuple(_failing_sources(session)),
        suggestions=(),
    )
    return _with_suggestions(report, len(relevant), _tech_counts(relevant, stack, None))


def format_weekly_message(report: WeeklyReport) -> str:
    first = report.period_start.strftime("%d/%m")
    last = report.period_end.strftime("%d/%m")
    lines = [f"📊 <b>Resumen semanal</b> · {first}–{last}"]

    lines += [
        "",
        "<b>Embudo</b>",
        f"🔎 {report.discovered} descubiertas → {report.passed_prefilter} pasan el filtro"
        f" → {report.evaluated} evaluadas",
        f"🔥 {report.apply} APPLY · 👀 {report.review} REVIEW",
        f"📨 {report.alerts_sent} alertas · 🗞️ {report.digest_items} en resúmenes diarios",
    ]

    if report.top_companies:
        lines += ["", "<b>Empresas con más ofertas relevantes</b>", _ranking(report.top_companies)]
    if report.top_sources:
        lines += ["", "<b>Fuentes con más ofertas relevantes</b>", _ranking(report.top_sources)]

    if report.technologies:
        lines += ["", "<b>Tecnologías en ofertas relevantes</b> (✅ = en tu stack)", _techs(report.technologies)]
    if report.technologies_saved:
        lines.append("👍 Guardadas: " + _techs(report.technologies_saved))
    if report.technologies_dismissed:
        lines.append("👎 Descartadas: " + _techs(report.technologies_dismissed))

    lines += ["", "<b>Salarios publicados</b>"]
    if report.salary is None:
        lines.append("Ninguna oferta relevante publica salario anual en EUR.")
    else:
        salary = report.salary
        lines += [
            f"{salary.count} de {salary.relevant} ofertas relevantes (EUR/año, sin conversión)",
            f"Mediana {_money(salary.median)} · mín {_money(salary.minimum)} · máx {_money(salary.maximum)}",
        ]

    lines += ["", "<b>Tu feedback</b>", f"👍 {report.thumbs_up} · 👎 {report.thumbs_down}"]
    if report.reasons_up:
        lines.append("👍 por: " + _ranking(report.reasons_up))
    if report.reasons_down:
        lines.append("👎 por: " + _ranking(report.reasons_down))

    if report.failing_sources:
        lines += ["", "⚠️ <b>Fuentes que fallan:</b> " + _html(", ".join(report.failing_sources), 500)]

    lines += ["", "<b>Sugerencias</b>"]
    if report.suggestions:
        lines += [f"• {_html(text, 220)}" for text in report.suggestions]
    else:
        lines.append("• Sin sugerencias: no hay suficientes datos esta semana.")
    return "\n".join(lines)


def preview_weekly(
    session: Session, candidate: CandidateConfig, *, now: datetime | None = None
) -> WeeklyResult:
    report = build_weekly_report(session, candidate, now=now)
    return WeeklyResult("preview", report, format_weekly_message(report))


def send_weekly(
    session: Session,
    candidate: CandidateConfig,
    provider: NotificationProvider,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> WeeklyResult:
    """Send at most one report per ~week; the marker is written only after delivery."""

    now = _aware(now or datetime.now(UTC))
    if not force:
        last = session.scalar(
            select(func.max(ReportDelivery.sent_at)).where(ReportDelivery.kind == WEEKLY_KIND)
        )
        if last is not None and now - _aware(last) < WEEKLY_MIN_INTERVAL:
            return WeeklyResult("too_soon")
    report = build_weekly_report(session, candidate, now=now)
    message = format_weekly_message(report)
    try:
        sent = provider.send_message(message)
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing
        session.rollback()
        return WeeklyResult("failed", report, message)
    session.add(
        ReportDelivery(
            kind=WEEKLY_KIND,
            period_start=report.period_start,
            period_end=report.period_end,
            provider_message_id=sent.message_id,
            sent_at=now,
        )
    )
    session.commit()
    return WeeklyResult("sent", report, message)


def _is_relevant(item: Opportunity) -> bool:
    return item.decision in (FinalDecision.APPLY, FinalDecision.REVIEW)


def _passed_prefilter(item: Opportunity) -> bool:
    result = item.deterministic_result
    return isinstance(result, dict) and result.get("decision") != PreFilterDecision.REJECT.value


def _candidate_stack(candidate: CandidateConfig) -> frozenset[str]:
    profile = candidate.profile
    return frozenset(
        name.casefold().strip()
        for name in (*profile.technologies, *profile.primary_skills, *profile.secondary_skills)
    )


def _discovered_count(session: Session, start: datetime, end: datetime) -> int:
    return session.scalar(
        select(func.count()).select_from(Job).where(Job.created_at >= start, Job.created_at <= end)
    ) or 0


def _sent_count(session: Session, channel: str, start: datetime, end: datetime) -> int:
    return session.scalar(
        select(func.count())
        .select_from(OpportunityNotification)
        .where(
            OpportunityNotification.channel == channel,
            OpportunityNotification.status == "SENT",
            OpportunityNotification.sent_at >= start,
            OpportunityNotification.sent_at <= end,
        )
    ) or 0


def _top_sources(session: Session, relevant: Iterable[Opportunity]) -> tuple[tuple[str, int], ...]:
    job_ids = [item.job_id for item in relevant]
    counter: Counter[str] = Counter()
    for offset in range(0, len(job_ids), 400):
        rows = session.execute(
            select(JobSource.job_id, JobSource.provider).where(JobSource.job_id.in_(job_ids[offset : offset + 400]))
        ).all()
        # A job seen through two sources counts once per provider, never twice for one.
        counter.update(provider for _job, provider in {(job, provider) for job, provider in rows})
    return tuple(counter.most_common(TOP_N))


def _items_of(reviews: Iterable[JobReview], by_id: dict) -> list[Opportunity]:
    return [by_id[row.job_id] for row in reviews if row.job_id in by_id]


def _tech_counts(
    items: Iterable[Opportunity], stack: frozenset[str], limit: int | None
) -> tuple[TechCount, ...]:
    counter: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for item in items:
        names = {name.strip() for name in (*item.technologies, *item.required_technologies) if name.strip()}
        keys = {}
        for name in names:
            keys.setdefault(name.casefold(), name)
        for key, name in keys.items():
            labels.setdefault(key, name)
            counter[key] += 1
    ranked = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))
    if limit is not None:
        ranked = ranked[:limit]
    return tuple(TechCount(labels[key], jobs, key in stack) for key, jobs in ranked)


def _salary_stats(relevant: list[Opportunity]) -> SalaryStats | None:
    """Yearly EUR figures only; monthly values are x12, other periods are skipped."""

    values: list[Decimal] = []
    lows: list[Decimal] = []
    highs: list[Decimal] = []
    for item in relevant:
        factor = _YEARLY_FACTOR.get((item.salary_period or "").upper())
        if factor is None or (item.currency or "").upper() != "EUR":
            continue
        low, high = _decimal(item.salary_min), _decimal(item.salary_max)
        published = [value * factor for value in (low, high) if value is not None]
        if not published:
            continue
        lows.append(min(published))
        highs.append(max(published))
        values.append(sum(published) / len(published))
    if not values:
        return None
    return SalaryStats(
        count=len(values),
        relevant=len(relevant),
        median=statistics.median(values),
        minimum=min(lows),
        maximum=max(highs),
    )


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def _reason_counts(reviews: Iterable[JobReview]) -> tuple[tuple[str, int], ...]:
    counter = Counter(_REASON_LABELS.get(row.reason or "", row.reason or _NO_REASON) for row in reviews)
    return tuple(counter.most_common(TOP_N))


def _with_suggestions(report: WeeklyReport, relevant_total: int, all_techs: tuple[TechCount, ...]) -> WeeklyReport:
    suggestions: list[str] = []
    if report.discovered == 0:
        suggestions.append("No se descubrió ninguna oferta nueva: revisa que las fuentes se estén consultando.")
    elif relevant_total == 0:
        suggestions.append(
            f"De {report.discovered} ofertas nuevas ninguna llegó a APPLY o REVIEW: "
            "puede que los filtros sean estrictos o que las fuentes no encajen."
        )
    gap = next(
        (
            tech
            for tech in all_techs
            if not tech.in_stack and tech.jobs >= MIN_TECH_JOBS and tech.jobs / relevant_total >= MIN_TECH_SHARE
        ),
        None,
    ) if relevant_total else None
    if gap is not None:
        suggestions.append(
            f"{gap.jobs} de {relevant_total} ofertas relevantes piden {gap.name}, que no está en tu stack: "
            "valora reforzarlo o añadirlo a tu perfil si ya lo dominas."
        )
    if report.reasons_down and report.thumbs_down:
        reason, count = report.reasons_down[0]
        if reason != _NO_REASON and count >= MIN_REASON_COUNT and count / report.thumbs_down >= MIN_REASON_SHARE:
            suggestions.append(
                f"{count} de tus {report.thumbs_down} 👎 son por «{reason}»: "
                "quizá convenga ajustar los filtros o preferencias en ese punto."
            )
    if report.failing_sources:
        suggestions.append(
            f"{len(report.failing_sources)} fuente(s) llevan varios fallos seguidos: "
            "revísalas o páusalas para no perder ofertas."
        )
    return replace(report, suggestions=tuple(suggestions[:3]))


def _ranking(pairs: Iterable[tuple[str, int]]) -> str:
    return " · ".join(f"{_html(name, 40)} ({count})" for name, count in pairs)


def _techs(techs: Iterable[TechCount]) -> str:
    return " · ".join(f"{'✅ ' if tech.in_stack else ''}{_html(tech.name, 30)} ({tech.jobs})" for tech in techs)


def _money(value: Decimal) -> str:
    return f"{int(value.to_integral_value()):,}".replace(",", ".") + " €"
