"""Review lifecycle for company job boards: discovered boards wait for a decision.

Company Intelligence already derives supported ATS boards from evidence
(company leads, observed job sources). This module records each board once,
in REVIEW_SOURCE, and only boards explicitly made ACTIVE are fetched by the
opportunity refresh. Fetch outcomes are recorded so the least recently
fetched boards are checked first.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.domain.company_intelligence import (
    ATSDiscoveryConfidence,
    ATSProvider,
    CompanyMonitorTarget,
    company_facts,
)
from ai_job_hunter.models import Company, MonitoredSource, MonitoredSourceState
from ai_job_hunter.services.company_intelligence import (
    CompanyMonitorFilters,
    company_matches_filters,
    public_board_url,
)

if TYPE_CHECKING:
    import httpx

    from ai_job_hunter.candidates import CandidateConfig
    from ai_job_hunter.domain.normalized_job import NormalizedJob
    from ai_job_hunter.services.opportunities import SourceFailure


class MonitoredSourceError(ValueError):
    """A safe, user-readable monitored-source error."""


@dataclass(frozen=True, slots=True)
class SyncSummary:
    created: int
    activated: int
    existing: int
    conflicts: int


def sync_monitored_sources(
    session: Session,
    *,
    activate_new: bool = False,
    reason: str | None = None,
    now: datetime | None = None,
) -> SyncSummary:
    """Record every supported board found in company evidence; never changes existing states.

    New boards start in REVIEW_SOURCE. ``activate_new`` exists for the one-time
    adoption of boards that were already being monitored before this lifecycle.
    """

    moment = now or datetime.now(UTC)
    existing = {
        (row.provider, row.identifier_key, row.region_key): row
        for row in session.scalars(select(MonitoredSource)).all()
    }
    companies = session.scalars(
        select(Company).options(selectinload(Company.evidence_items)).order_by(Company.name)
    ).all()
    counts: Counter[str] = Counter()
    for company in companies:
        for discovery in company_facts(company).ats_discoveries:
            if not discovery.is_supported or discovery.identifier is None:
                continue
            key = (discovery.provider.value, discovery.identifier.casefold(), discovery.region or "")
            row = existing.get(key)
            if row is not None:
                counts["conflicts" if row.company_id != company.id else "existing"] += 1
                continue
            state = MonitoredSourceState.ACTIVE if activate_new else MonitoredSourceState.REVIEW_SOURCE
            observed = discovery.confidence is ATSDiscoveryConfidence.OBSERVED_JOB_SOURCE
            board_url = public_board_url(discovery.provider, discovery.identifier, discovery.region)
            row = MonitoredSource(
                company_id=company.id,
                provider=discovery.provider.value,
                identifier=discovery.identifier,
                identifier_key=key[1],
                region=discovery.region,
                region_key=key[2],
                # An observed source URL points at one posting; show the board instead.
                careers_url=board_url if observed else (discovery.source_url or board_url),
                state=state.value,
                state_reason=reason if activate_new else "Discovered; waiting for review.",
                state_changed_at=moment,
                origin="observed_job_source" if observed else "career_url",
            )
            session.add(row)
            existing[key] = row
            counts["activated" if activate_new else "created"] += 1
    session.commit()
    return SyncSummary(
        created=counts["created"],
        activated=counts["activated"],
        existing=counts["existing"],
        conflicts=counts["conflicts"],
    )


def set_source_state(
    session: Session,
    source_id: UUID,
    state: MonitoredSourceState,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> MonitoredSource:
    row = session.get(MonitoredSource, source_id)
    if row is None:
        raise MonitoredSourceError(f"Unknown monitored source id: {source_id}.")
    if row.state != state.value:
        row.state = state.value
        row.state_changed_at = now or datetime.now(UTC)
    row.state_reason = reason.strip() if reason and reason.strip() else row.state_reason
    if state is MonitoredSourceState.ACTIVE:
        row.consecutive_failures = 0
    session.commit()
    return row


def list_sources(session: Session, *, state: MonitoredSourceState | None = None) -> list[MonitoredSource]:
    query = select(MonitoredSource).options(joinedload(MonitoredSource.company))
    if state is not None:
        query = query.where(MonitoredSource.state == state.value)
    rows = session.scalars(query).all()
    return sorted(rows, key=lambda row: (row.state, row.company.name.casefold(), row.provider, row.identifier_key))


# Providers polled less often than every run. Lever's API stopped accepting
# connections from the server after a day of 15-minute polling (2026-10-04).
# Careers sites (sitemap + JobPosting pages) and Amazon change slowly and should
# not be hit every 15 minutes.
PROVIDER_MIN_INTERVAL = {
    "LEVER": timedelta(hours=2),
    "CAREERS_SITE": timedelta(hours=3),
    "AMAZON_JOBS": timedelta(hours=4),
}


def active_monitor_targets(
    session: Session,
    filters: CompanyMonitorFilters | None = None,
    *,
    limit_companies: int = 10,
    now: datetime | None = None,
) -> list[CompanyMonitorTarget]:
    """ACTIVE boards, least recently fetched first, optionally narrowed by company facts.

    Boards of a provider in PROVIDER_MIN_INTERVAL are skipped until that much
    time has passed since their last fetch (successful or not).
    """

    if limit_companies < 1:
        raise ValueError("limit_companies must be positive")
    rows = session.scalars(
        select(MonitoredSource)
        .options(joinedload(MonitoredSource.company).selectinload(Company.evidence_items))
        .where(MonitoredSource.state == MonitoredSourceState.ACTIVE.value)
    ).unique().all()
    never = datetime.min.replace(tzinfo=UTC)
    rows = sorted(
        rows,
        key=lambda row: (
            _as_utc(row.last_fetched_at) or never,
            row.company.name.casefold(),
            row.provider,
            row.identifier_key,
        ),
    )
    targets: list[CompanyMonitorTarget] = []
    companies: set[UUID] = set()
    current = now or datetime.now(UTC)
    for row in rows:
        interval = PROVIDER_MIN_INTERVAL.get(row.provider.upper())
        last = _as_utc(row.last_fetched_at)
        if interval is not None and last is not None and current - last < interval:
            continue
        if filters is not None and not company_matches_filters(company_facts(row.company), filters):
            continue
        if row.company_id not in companies and len(companies) >= limit_companies:
            continue
        companies.add(row.company_id)
        provider = ATSProvider(row.provider)
        targets.append(
            CompanyMonitorTarget(
                company_id=row.company_id,
                company_name=row.company.name,
                provider=provider,
                identifier=row.identifier,
                region=row.region,
                careers_url=row.careers_url or public_board_url(provider, row.identifier, row.region),
                evidence_source=row.origin,
                confidence=(
                    ATSDiscoveryConfidence.OBSERVED_JOB_SOURCE
                    if row.origin == "observed_job_source"
                    else ATSDiscoveryConfidence.DIRECT_URL_PATTERN
                ),
                source_id=row.id,
                known_urls=_known_job_urls(session, row) if provider is ATSProvider.CAREERS_SITE else frozenset(),
            )
        )
    return targets


def _known_job_urls(session: Session, row: MonitoredSource) -> frozenset[str]:
    """Job page URLs already stored for the company's careers-site postings (never closed, see below)."""

    from ai_job_hunter.models import Job, JobSource

    return frozenset(
        session.scalars(
            select(JobSource.canonical_url)
            .join(Job, Job.id == JobSource.job_id)
            .where(
                Job.company_id == row.company_id,
                JobSource.provider == "careers_site",
                JobSource.canonical_url.is_not(None),
            )
        ).all()
    )


def record_fetch_results(
    session: Session,
    targets: Sequence[CompanyMonitorTarget],
    offers: Iterable[tuple["NormalizedJob", CompanyMonitorTarget]],
    failures: Iterable["SourceFailure"],
    *,
    now: datetime | None = None,
) -> None:
    """Store when each board was fetched and how it went (for rotation and health)."""

    moment = now or datetime.now(UTC)
    counts = Counter(
        target.source_id for _offer, target in offers if target is not None and target.source_id is not None
    )
    failed = {(failure.company, failure.provider.casefold()): failure.error_type for failure in failures}
    for target in targets:
        if target.source_id is None:
            continue
        row = session.get(MonitoredSource, target.source_id)
        if row is None:
            continue
        row.last_fetched_at = moment
        error = failed.get((target.company_name, target.provider.value.casefold()))
        if error is None:
            row.last_fetch_status = "OK"
            row.last_fetch_error = None
            row.last_job_count = counts.get(target.source_id, 0)
            row.consecutive_failures = 0
        else:
            row.last_fetch_status = "FAILED"
            row.last_fetch_error = error[:100]
            row.consecutive_failures += 1
    session.commit()


def preview_source(
    session: Session,
    source_id: UUID,
    candidate: "CandidateConfig",
    *,
    client: "httpx.Client | None" = None,
    max_jobs: int = 500,
    now: datetime | None = None,
) -> dict[str, object]:
    """Fetch one board once and summarize how its jobs fare against the prefilter.

    Nothing is ingested and Jev is not called; only the summary is stored on
    the source row so the activation decision is explainable.
    """

    from ai_job_hunter.candidates import JobFacts, PreFilterDecision, evaluate_job
    from ai_job_hunter.candidates.prefilter import RoleFamilyFit, SignalStatus
    from ai_job_hunter.connectors.factory import build_job_connectors
    from ai_job_hunter.job_sources import JobSourceSpec, JobSourcesConfig

    row = session.get(MonitoredSource, source_id)
    if row is None:
        raise MonitoredSourceError(f"Unknown monitored source id: {source_id}.")
    spec = JobSourceSpec(
        provider=row.provider.casefold(),
        identifier=row.identifier,
        company_name=row.company.name,
        region=row.region,
        max_jobs=max_jobs,
    )
    (connector,) = build_job_connectors(JobSourcesConfig(sources=[spec]), client=client)
    try:
        jobs = connector.fetch_jobs()
    except Exception as error:  # Connector errors never include credentials; report the type.
        stats: dict[str, object] = {"error": type(error).__name__}
    else:
        results = [(job, evaluate_job(JobFacts.from_normalized_job(job), candidate)) for job in jobs]
        passing = [(job, result) for job, result in results if result.decision is not PreFilterDecision.REJECT]
        stats = {
            "jobs": len(jobs),
            "geography_compatible": sum(
                result.signals.geography.status is SignalStatus.COMPATIBLE for _job, result in results
            ),
            "target_role_family": sum(
                result.signals.role_family.fit is RoleFamilyFit.TARGET for _job, result in results
            ),
            "prefilter_pass_or_review": len(passing),
            "examples": [f"{job.title} — {job.location or 'location n/a'}" for job, _result in passing[:5]],
        }
    stats["previewed_at"] = (now or datetime.now(UTC)).isoformat(timespec="minutes")
    row.preview_stats = stats
    session.commit()
    return stats


AUTO_ACTIVATE_RECHECK = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class AutoActivation:
    source_id: UUID
    company: str
    board: str
    outcome: str  # "activated", "kept", "error"
    relevant: int


def auto_activate_sources(
    session: Session,
    candidate: "CandidateConfig",
    *,
    limit: int = 30,
    min_relevant: int = 1,
    dry_run: bool = False,
    force: bool = False,
    client: "httpx.Client | None" = None,
    now: datetime | None = None,
) -> list[AutoActivation]:
    """Preview REVIEW_SOURCE boards and activate those with relevant jobs.

    A board is activated when its preview has at least ``min_relevant`` jobs
    that the deterministic prefilter does not reject (role family, location,
    seniority and experience all allow them). Boards without any stay in
    review and are re-checked after AUTO_ACTIVATE_RECHECK. Rejected or paused
    boards are never touched. The decision and its numbers are kept on the
    row (state_reason, preview_stats) so it stays explainable.
    """

    current = now or datetime.now(UTC)
    rows = list_sources(session, state=MonitoredSourceState.REVIEW_SOURCE)

    def last_preview(row: MonitoredSource) -> datetime | None:
        stats = row.preview_stats if isinstance(row.preview_stats, dict) else {}
        value = stats.get("previewed_at")
        try:
            return _as_utc(datetime.fromisoformat(value)) if isinstance(value, str) else None
        except ValueError:
            return None

    due = [
        row
        for row in rows
        if force or last_preview(row) is None or current - last_preview(row) >= AUTO_ACTIVATE_RECHECK
    ]
    due.sort(key=lambda row: last_preview(row) or datetime.min.replace(tzinfo=UTC))
    results: list[AutoActivation] = []
    for row in due[:limit]:
        source_id, company, board = row.id, row.company.name, f"{row.provider}:{row.identifier}"
        stats = preview_source(session, source_id, candidate, client=client, now=current)
        if "error" in stats:
            results.append(AutoActivation(source_id, company, board, "error", 0))
            continue
        relevant = int(stats.get("prefilter_pass_or_review") or 0)
        if relevant >= min_relevant and not dry_run:
            set_source_state(
                session,
                source_id,
                MonitoredSourceState.ACTIVE,
                reason=f"auto-activated: {relevant} relevant job(s) of {stats.get('jobs')} in preview",
                now=current,
            )
            results.append(AutoActivation(source_id, company, board, "activated", relevant))
        else:
            results.append(AutoActivation(source_id, company, board, "kept", relevant))
    return results


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def mark_closed_postings(
    session: Session,
    targets: Sequence[CompanyMonitorTarget],
    offers: Iterable[tuple["NormalizedJob", CompanyMonitorTarget | None]],
    failures: Iterable["SourceFailure"],
    *,
    seen_source_ids: set[UUID],
    max_jobs_per_company: int,
    now: datetime | None = None,
) -> int:
    """Mark postings that a complete, successful board fetch no longer lists as closed.

    Conservative: boards that failed, returned nothing (possible glitch) or hit
    the per-company job limit (truncated listing) never close anything.
    Re-listed postings are reopened by ingestion.
    """

    from ai_job_hunter.models import Job, JobSource

    moment = now or datetime.now(UTC)
    counts = Counter(target.source_id for _offer, target in offers if target is not None and target.source_id)
    failed = {(failure.company, failure.provider.casefold()) for failure in failures}
    closed = 0
    for target in targets:
        count = counts.get(target.source_id, 0)
        if target.source_id is None or (target.company_name, target.provider.value.casefold()) in failed:
            continue
        if target.provider is ATSProvider.CAREERS_SITE:
            continue  # Each run returns only unseen job pages, never the whole board.
        if count == 0 or count >= max_jobs_per_company:
            continue
        stale = session.scalars(
            select(JobSource)
            .join(Job, Job.id == JobSource.job_id)
            .where(
                Job.company_id == target.company_id,
                JobSource.provider == target.provider.value.casefold(),
                JobSource.closed_at.is_(None),
            )
        ).all()
        for source in stale:
            if source.id in seen_source_ids:
                continue
            source.closed_at = moment
            closed += 1
    session.commit()
    return closed
