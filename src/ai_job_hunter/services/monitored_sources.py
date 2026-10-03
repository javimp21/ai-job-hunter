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
from datetime import UTC, datetime
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


def active_monitor_targets(
    session: Session,
    filters: CompanyMonitorFilters | None = None,
    *,
    limit_companies: int = 10,
) -> list[CompanyMonitorTarget]:
    """ACTIVE boards, least recently fetched first, optionally narrowed by company facts."""

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
    for row in rows:
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
            )
        )
    return targets


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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
