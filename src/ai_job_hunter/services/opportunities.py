"""Refresh and query a persistent opportunity feed.

This service composes the existing public ATS connectors, ingestion/deduplication,
deterministic prefilter, Jev cache and versioned decision policy. User review and
application state are deliberately maintained in separate rows from evaluations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.candidates import (
    CandidateConfig,
    JobFacts,
    JobPreFilterResult,
    PreFilterDecision,
    evaluate_job,
)
from ai_job_hunter.candidates.experience import ExperienceAssessment, ExperienceOutcome
from ai_job_hunter.candidates.prefilter import SignalStatus
from ai_job_hunter.connectors.ashby import AshbyConnectorError
from ai_job_hunter.connectors.factory import build_job_connectors
from ai_job_hunter.connectors.greenhouse import GreenhouseConnectorError
from ai_job_hunter.connectors.lever import LeverConnectorError
from ai_job_hunter.connectors.smartrecruiters import SmartRecruitersConnectorError
from ai_job_hunter.connectors.teamtailor import TeamtailorConnectorError
from ai_job_hunter.decision_engine import (
    POLICY_VERSION_V2,
    RUBRIC_VERSION,
    DecisionCache,
    FinalDecision,
    JobDecisionContext,
    JobDecisionEngine,
    JobDecisionError,
    JobDecisionResult,
    apply_versioned_decision_policy,
    evaluate_job_decision,
)
from ai_job_hunter.deduplication.matcher import DeduplicationDecision, match_job
from ai_job_hunter.deduplication.normalization import normalize_company_name, normalize_job_title
from ai_job_hunter.domain.company_intelligence import (
    CompanyFacts,
    CompanyMonitorTarget,
    FactStatus,
    company_facts,
)
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)
from ai_job_hunter.job_sources import JobSourceSpec, JobSourcesConfig
from ai_job_hunter.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    EvaluationStatus,
    HumanReviewStatus,
    Job,
    JobEvaluation,
    JobReview,
    JobSource,
)
from ai_job_hunter.models.company import Company
from ai_job_hunter.models.outreach import Outreach, OutreachStatus
from ai_job_hunter.outreach.recommendations import (
    OutreachRecommendation,
    recommend_outreach,
)
from ai_job_hunter.services.company_intelligence import (
    CompanyMonitorFilters,
    get_company_facts_for_job,
)
from ai_job_hunter.services.ingestion import IngestionResult, IngestionStatus, ingest_job
from ai_job_hunter.services.job_portals import (
    DEFAULT_STATE_PATH as DEFAULT_PORTAL_STATE_PATH,
    due_portals,
    fetch_portals,
)
from ai_job_hunter.services.monitored_sources import (
    active_monitor_targets,
    record_fetch_results,
    sync_monitored_sources,
)
from ai_job_hunter.jev import JevJobDecisionEngine
from ai_job_hunter.rubric import RUBRIC_SPEC


_ENGINE_NAME = "typesafe-jev"
_DETERMINISTIC_ENGINE_NAME = "deterministic-prefilter"
_PREFILTER_VERSION = "candidate-prefilter-v4-role-family"
_REASON_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_APPLICATION_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: frozenset({ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.APPLIED: frozenset(
        {ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
    ),
    ApplicationStatus.INTERVIEW: frozenset(
        {ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
    ),
    ApplicationStatus.OFFER: frozenset({ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.REJECTED: frozenset(),
    ApplicationStatus.WITHDRAWN: frozenset(),
}


class OpportunityServiceError(ValueError):
    """A safe, user-readable opportunity workflow error."""


@dataclass(frozen=True, slots=True)
class SourceFailure:
    company: str
    provider: str
    error_type: str


@dataclass(slots=True)
class RefreshSummary:
    companies_checked: int = 0
    portals_checked: int = 0
    jobs_fetched: int = 0
    new_jobs: int = 0
    known_jobs: int = 0
    changed_jobs: int = 0
    hard_skips: int = 0
    jev_calls: int = 0
    jev_evaluated: int = 0
    jev_cache_hits: int = 0
    pending: int = 0
    pending_budget: int = 0
    pending_no_jev: int = 0
    pending_errors: int = 0
    apply: int = 0
    review: int = 0
    skip: int = 0
    dry_run: bool = False
    failures: list[SourceFailure] = field(default_factory=list)


class EvaluationOutcome(StrEnum):
    """What the evaluation loop did (or, in a dry run, would do) for one snapshot."""

    CURRENT = "CURRENT"
    DETERMINISTIC_SKIP = "DETERMINISTIC_SKIP"
    CACHE_HIT = "CACHE_HIT"
    JEV_CALL = "JEV_CALL"
    PENDING_BUDGET = "PENDING_BUDGET"
    PENDING_NO_JEV = "PENDING_NO_JEV"
    PENDING_ERROR = "PENDING_ERROR"


@dataclass(frozen=True, slots=True)
class EvaluationItemResult:
    job_id: UUID
    company: str | None
    title: str
    outcome: EvaluationOutcome
    decision: str | None = None


@dataclass(slots=True)
class ReevaluationSummary(RefreshSummary):
    jobs_selected: int = 0
    items: list[EvaluationItemResult] = field(default_factory=list)
    jobs_without_snapshot: list[UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Opportunity:
    job_id: UUID
    title: str
    company: str
    location: str | None
    remote_policy: str | None
    employment_type: str | None
    url: str | None
    technologies: tuple[str, ...]
    required_technologies: tuple[str, ...]
    salary_min: str | None
    salary_max: str | None
    currency: str | None
    salary_period: str | None
    published_at: datetime | None
    decision: FinalDecision | None
    evaluation_status: EvaluationStatus | None
    evaluation_is_stale: bool
    review_state: HumanReviewStatus
    application_status: ApplicationStatus | None
    priority: int | None
    deterministic_result: dict[str, Any] | None
    jev_signals: dict[str, Any] | None
    jev_reasons: dict[str, Any] | list[Any] | None
    company_facts: CompanyFacts | None = None
    outreach_recommendation: OutreachRecommendation = OutreachRecommendation.NO_OUTREACH
    evaluation_fingerprint: str | None = None
    experience: ExperienceAssessment | None = None
    # Human-readable soft-preference changes already applied to `priority`.
    priority_adjustments: tuple[str, ...] = ()
    # When this job was first seen by the hunter (fallback when a source gives no date).
    first_seen_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _PreparedOffer:
    offer: NormalizedJob
    context: JobDecisionContext
    fingerprint: str
    config_fingerprint: str
    job_id: UUID | None = None


def refresh_opportunities(
    session: Session,
    candidate: CandidateConfig,
    *,
    max_companies: int = 10,
    max_jobs_per_company: int = 100,
    max_jev_jobs: int = 20,
    no_jev: bool = False,
    retry_pending: bool = False,
    dry_run: bool = False,
    candidate_filters: CompanyMonitorFilters | None = None,
    cache: DecisionCache | None = None,
    engine: JobDecisionEngine | None = None,
    client: httpx.Client | None = None,
    portals: Sequence[str] = (),
    portal_state_path: Path = DEFAULT_PORTAL_STATE_PATH,
) -> RefreshSummary:
    """Fetch monitored ATS boards and due job portals, ingest, then evaluate new/stale snapshots.

    The caller supplies a clean SQLAlchemy Session. The existing ``ingest_job``
    function owns its per-offer transaction, so reads are ended before ingestion
    and each offer commits independently. A provider/API failure is reported by
    type only; request details, raw payloads and credentials are not included.
    """

    if max_companies < 1:
        raise OpportunityServiceError("max_companies must be positive.")
    if max_jobs_per_company < 1:
        raise OpportunityServiceError("max_jobs_per_company must be positive.")
    if max_jev_jobs < 0:
        raise OpportunityServiceError("max_jev_jobs cannot be negative.")
    _require_clean_session_for_owned_transactions(session)

    summary = RefreshSummary(dry_run=dry_run)
    filters = candidate_filters or CompanyMonitorFilters(supported_ats=True)
    if not dry_run:
        # Newly discovered boards are recorded for review; they are never fetched
        # until someone makes them ACTIVE.
        sync_monitored_sources(session)
    try:
        targets = active_monitor_targets(session, filters, limit_companies=max_companies)
    except ValueError as error:
        raise OpportunityServiceError(str(error)) from error
    summary.companies_checked = len({target.company_id for target in targets})
    session.rollback()  # End the read transaction before any connector or ingest work.
    due = due_portals(portals, state_path=portal_state_path) if portals else []
    if not targets and not due:
        return summary

    offers: list[tuple[NormalizedJob, CompanyMonitorTarget | None]]
    offers, failures = (
        _fetch_targets(targets, max_jobs_per_company=max_jobs_per_company, client=client)
        if targets
        else ([], [])
    )
    summary.failures.extend(failures)
    if not dry_run:
        record_fetch_results(session, targets, offers, failures)
    if due:
        # Portal offers have no company board; ingestion matches/creates the company.
        portal_offers, portal_failures = fetch_portals(
            due, client=client, state_path=portal_state_path, record=not dry_run
        )
        offers.extend((offer, None) for offer in portal_offers)
        summary.portals_checked = len(due)
        summary.failures.extend(
            SourceFailure(failure.portal, "PORTAL", failure.error_type) for failure in portal_failures
        )
    summary.jobs_fetched = len(offers)

    if dry_run:
        for offer, _target in offers:
            prepared = _prepare_offer(offer, candidate, engine_identity=_engine_identity(engine))
            if prepared.context.deterministic.decision is PreFilterDecision.REJECT:
                summary.hard_skips += 1
            else:
                summary.pending += 1
        return summary

    active_cache = cache or DecisionCache()
    active_engine = engine or JevJobDecisionEngine()
    # Validate a user-supplied engine's cache identity before mutating the DB.
    try:
        engine_identity = active_engine.cache_identity
    except Exception as error:
        raise OpportunityServiceError(f"Cannot initialize Jev engine ({type(error).__name__}).") from error

    prepared_by_job: dict[UUID, dict[str, _PreparedOffer]] = {}
    baseline_jobs = session.scalars(
        select(Job)
        .options(joinedload(Job.company), selectinload(Job.sources))
        .order_by(Job.id)
    ).unique().all()
    jobs_existing_before_refresh = {job.id for job in baseline_jobs}
    prior_fingerprints: dict[UUID, set[str]] = {
        job.id: {
            item.fingerprint
            for item in _source_context_fingerprints(job, candidate, engine_identity)
        }
        for job in baseline_jobs
    }
    session.rollback()
    created_ids: set[UUID] = set()
    touched_ids: set[UUID] = set()

    for offer, _target in offers:
        old_match_id, _old_fingerprints = _find_existing_match_fingerprints(
            session,
            offer,
            candidate,
            engine_identity,
        )
        if old_match_id is not None and old_match_id not in jobs_existing_before_refresh:
            old_match_id = None
        session.rollback()
        try:
            ingested = ingest_job(session, offer)
        except Exception as error:
            summary.failures.append(
                SourceFailure(
                    company=offer.company_name or "Unknown company",
                    provider=offer.provider.upper(),
                    error_type=type(error).__name__,
                )
            )
            continue

        job_id = ingested.job_id
        touched_ids.add(job_id)
        if ingested.status in {IngestionStatus.CREATED, IngestionStatus.POSSIBLE_MATCH}:
            created_ids.add(job_id)
        if old_match_id is not None and old_match_id != job_id:
            # Deduplication made a different identity decision than the read-only
            # precheck. Don't merge or transfer any user state in this workflow.
            old_match_id = None

        _ensure_review_row(session, job_id)
        try:
            prepared = _prepare_persisted_source(
                session,
                job_id,
                offer,
                candidate,
                engine_identity,
            )
        except Exception as error:
            summary.failures.append(
                SourceFailure(
                    company=offer.company_name or "Unknown company",
                    provider=offer.provider.upper(),
                    error_type=type(error).__name__,
                )
            )
            continue
        if prepared is not None:
            prepared_by_job.setdefault(job_id, {})[prepared.fingerprint] = prepared
        session.rollback()

    summary.new_jobs = len(created_ids)
    summary.known_jobs = len(touched_ids - created_ids)
    summary.changed_jobs = sum(
        1
        for job_id, snapshots in prepared_by_job.items()
        if job_id in jobs_existing_before_refresh
        and any(fingerprint not in prior_fingerprints.get(job_id, set()) for fingerprint in snapshots)
    )

    _evaluate_prepared(
        session,
        (item for snapshots in prepared_by_job.values() for item in snapshots.values()),
        summary,
        engine=active_engine,
        cache=active_cache,
        engine_identity=engine_identity,
        max_jev_jobs=max_jev_jobs,
        no_jev=no_jev,
        retry_pending=retry_pending,
    )
    return summary


def reevaluate_jobs(
    session: Session,
    candidate: CandidateConfig,
    job_ids: Iterable[UUID],
    *,
    max_jev_jobs: int,
    dry_run: bool = False,
    cache: DecisionCache | None = None,
    engine: JobDecisionEngine | None = None,
) -> ReevaluationSummary:
    """Re-evaluate explicitly selected persisted jobs without fetching any source.

    Only the selected jobs' stored source snapshots are prepared, so other
    stale or unevaluated jobs are never touched. Evaluation reuses the refresh
    work loop: current evaluations are reused, deterministic rejects never call
    Jev, and each new Jev attempt is counted before it is made. Explicit
    selection retries budget-deferred PENDING work. ``dry_run`` reads only: it
    neither writes evaluations nor calls Jev nor writes the decision cache.
    """

    if max_jev_jobs < 0:
        raise OpportunityServiceError("max_jev_jobs cannot be negative.")
    selected = list(dict.fromkeys(job_ids))
    if not selected:
        raise OpportunityServiceError("Select at least one job id.")
    _require_clean_session_for_owned_transactions(session)

    active_cache = cache or DecisionCache()
    active_engine = engine or JevJobDecisionEngine()
    try:
        engine_identity = active_engine.cache_identity
    except Exception as error:
        raise OpportunityServiceError(f"Cannot initialize Jev engine ({type(error).__name__}).") from error

    jobs = {
        job.id: job
        for job in session.scalars(
            select(Job)
            .options(joinedload(Job.company), selectinload(Job.sources))
            .where(Job.id.in_(selected))
        ).unique().all()
    }
    missing = [str(job_id) for job_id in selected if job_id not in jobs]
    if missing:
        session.rollback()
        raise OpportunityServiceError("Unknown job id(s): " + ", ".join(missing) + ".")
    snapshots_by_job = {
        job_id: _source_context_fingerprints(jobs[job_id], candidate, engine_identity)
        for job_id in selected
    }
    session.rollback()
    prepared = [item for snapshots in snapshots_by_job.values() for item in snapshots]

    summary = ReevaluationSummary(
        dry_run=dry_run,
        jobs_selected=len(selected),
        jobs_without_snapshot=[job_id for job_id, snapshots in snapshots_by_job.items() if not snapshots],
    )
    summary.items = _evaluate_prepared(
        session,
        prepared,
        summary,
        engine=active_engine,
        cache=active_cache,
        engine_identity=engine_identity,
        max_jev_jobs=max_jev_jobs,
        no_jev=False,
        retry_pending=True,
        dry_run=dry_run,
    )
    return summary


class _CacheOnlyEngine:
    """Engine for cache hits: never calls Jev, so the budget cannot be bypassed.

    If the cache entry disappears between the lookup and the read (for example,
    another process rewrote the file), the item becomes a retryable error.
    """

    def __init__(self, engine: JobDecisionEngine) -> None:
        self._engine = engine

    @property
    def cache_identity(self) -> str:
        return self._engine.cache_identity

    def evaluate(self, context: JobDecisionContext):
        raise JobDecisionError("Cached decision disappeared; Jev was not called outside the budget.")


def _evaluate_prepared(
    session: Session,
    items: Iterable[_PreparedOffer],
    summary: RefreshSummary,
    *,
    engine: JobDecisionEngine,
    cache: DecisionCache,
    engine_identity: str,
    max_jev_jobs: int,
    no_jev: bool,
    retry_pending: bool,
    dry_run: bool = False,
) -> list[EvaluationItemResult]:
    """Evaluate prepared snapshots; shared by refresh and targeted reevaluation.

    With ``dry_run`` every item is classified exactly as a real run would
    classify it, including the Jev budget, but nothing is persisted, Jev is not
    called and cached results are not loaded.
    """

    # Work order is fixed across runs: deterministic PASS before REVIEW, then
    # published date, company/title, and persistent UUID. Cached work is never
    # blocked by the new-call budget.
    prepared = sorted(items, key=_evaluation_order)
    results: list[EvaluationItemResult] = []

    def record(item: _PreparedOffer, outcome: EvaluationOutcome, decision: str | None = None) -> None:
        results.append(EvaluationItemResult(
            job_id=_required_job_id(item),
            company=item.offer.company_name,
            title=item.offer.title,
            outcome=outcome,
            decision=decision,
        ))

    jev_calls = 0
    for item in prepared:
        existing = _evaluation_for_fingerprint(session, item)
        if (
            existing is not None
            and existing[0] == EvaluationStatus.EVALUATED.value
            and item.context.deterministic.decision is not PreFilterDecision.REJECT
        ):
            saved_decision = existing[1]
            if saved_decision == FinalDecision.APPLY.value and item.context.deterministic.signals.experience.outcome is not ExperienceOutcome.MEETS:
                saved_decision = FinalDecision.REVIEW.value
            session.rollback()
            _count_decision(summary, saved_decision)
            record(item, EvaluationOutcome.CURRENT, saved_decision)
            continue
        session.rollback()
        if item.context.deterministic.decision is PreFilterDecision.REJECT:
            summary.hard_skips += 1
            if not dry_run:
                result = _evaluate_hard_skip(item.context, engine_identity)
                _persist_evaluation(session, item, result, engine_name=_DETERMINISTIC_ENGINE_NAME)
            summary.skip += 1
            record(item, EvaluationOutcome.DETERMINISTIC_SKIP, FinalDecision.SKIP.value)
            continue

        cache_key = cache.key_for(item.context, engine_identity, RUBRIC_VERSION)
        cached = cache.contains(cache_key)
        if cached:
            if dry_run:
                summary.jev_cache_hits += 1
                record(item, EvaluationOutcome.CACHE_HIT)
                continue
            try:
                result = evaluate_job_decision(
                    item.context,
                    _CacheOnlyEngine(engine),
                    cache=cache,
                    policy_version=POLICY_VERSION_V2,
                )
            except JobDecisionError as error:
                _persist_pending(
                    session,
                    item,
                    engine_identity,
                    f"Decision cache/evaluation error ({type(error).__name__}).",
                )
                summary.pending += 1
                summary.pending_errors += 1
                record(item, EvaluationOutcome.PENDING_ERROR)
                continue
            summary.jev_cache_hits += 1
            _persist_evaluation(session, item, result, engine_name=_ENGINE_NAME)
            _count_decision(summary, result.final_decision)
            record(item, EvaluationOutcome.CACHE_HIT, result.final_decision.value)
            continue

        pending_budget_limit = None
        if (
            existing is not None
            and existing[0] == EvaluationStatus.PENDING.value
            and isinstance(existing[2], dict)
        ):
            prior_limit = existing[2].get("pending_budget_limit")
            if isinstance(prior_limit, int) and not isinstance(prior_limit, bool):
                pending_budget_limit = prior_limit
        if (
            not no_jev
            and not retry_pending
            and pending_budget_limit is not None
            and max_jev_jobs <= pending_budget_limit
        ):
            # Keep an identical budget-limited refresh idempotent. Raise the
            # budget or pass retry_pending to explicitly resume deferred work.
            summary.pending += 1
            summary.pending_budget += 1
            record(item, EvaluationOutcome.PENDING_BUDGET)
            continue

        if no_jev or jev_calls >= max_jev_jobs:
            reason = "Jev disabled by --no-jev." if no_jev else "Pending: --max-jev-jobs budget reached."
            if not dry_run:
                _persist_pending(
                    session,
                    item,
                    engine_identity,
                    reason,
                    budget_limit=None if no_jev else max_jev_jobs,
                )
            summary.pending += 1
            if no_jev:
                summary.pending_no_jev += 1
                record(item, EvaluationOutcome.PENDING_NO_JEV)
            else:
                summary.pending_budget += 1
                record(item, EvaluationOutcome.PENDING_BUDGET)
            continue

        # Count the attempt before calling out so provider failures cannot
        # exceed the configured number of attempted new requests.
        jev_calls += 1
        if dry_run:
            record(item, EvaluationOutcome.JEV_CALL)
            continue
        summary.jev_calls += 1
        try:
            result = evaluate_job_decision(
                item.context,
                engine,
                cache=cache,
                policy_version=POLICY_VERSION_V2,
            )
        except JobDecisionError as error:
            # Jev errors are intentionally contained per offer. The pending row
            # has no decision and can be retried at the next refresh.
            _persist_pending(session, item, engine_identity, f"Jev unavailable ({type(error).__name__}).")
            summary.pending += 1
            summary.pending_errors += 1
            record(item, EvaluationOutcome.PENDING_ERROR)
            continue
        summary.jev_evaluated += 1
        _persist_evaluation(session, item, result, engine_name=_ENGINE_NAME)
        _count_decision(summary, result.final_decision)
        record(item, EvaluationOutcome.JEV_CALL, result.final_decision.value)

    return results


def list_opportunities(
    session: Session,
    candidate: CandidateConfig,
    *,
    decision: FinalDecision | None = None,
    status: HumanReviewStatus | None = None,
    remote_only: bool = False,
    company: str | None = None,
    technology: str | None = None,
    limit: int = 20,
    engine: JobDecisionEngine | None = None,
    include_applied: bool = False,
    include_skip: bool = False,
    include_dismissed: bool = False,
) -> list[Opportunity]:
    """Build a stable feed without invoking Jev or changing persistent state."""

    if limit < 1:
        raise OpportunityServiceError("limit must be positive.")
    identity = _engine_identity(engine)
    config_fp = _config_fingerprint(candidate, identity)
    jobs = session.scalars(
        select(Job)
        .options(
            joinedload(Job.company).selectinload(Company.evidence_items),
            selectinload(Job.sources),
        )
        .order_by(Job.id)
    ).unique().all()
    reviews = {
        row.job_id: row
        for row in session.scalars(select(JobReview)).all()
    }
    applications = {
        row.job_id: row
        for row in session.scalars(select(Application)).all()
    }
    active_outreach_jobs = {
        job_id
        for job_id in session.scalars(
            select(Outreach.job_id).where(
                Outreach.job_id.is_not(None),
                Outreach.status.in_(
                    (
                        OutreachStatus.DRAFT.value,
                        OutreachStatus.APPROVED.value,
                        OutreachStatus.SENT.value,
                        OutreachStatus.REPLIED.value,
                    )
                ),
            )
        ).all()
        if job_id is not None
    }
    evaluations_by_job: dict[UUID, list[JobEvaluation]] = {}
    for row in session.scalars(
        select(JobEvaluation).order_by(JobEvaluation.created_at.desc(), JobEvaluation.id.desc())
    ).all():
        evaluations_by_job.setdefault(row.job_id, []).append(row)

    output: list[tuple[tuple[Any, ...], Opportunity]] = []
    company_filter = normalize_company_name(company) if company else None
    tech_filter = technology.casefold().strip() if technology else None
    for job in jobs:
        source_snapshots = [
            _prepare_from_source(job, source, candidate, identity)
            for source in sorted(job.sources, key=_source_order)
        ]
        source_snapshots = [item for item in source_snapshots if item is not None]
        if not source_snapshots:
            continue
        fingerprints = {item.fingerprint for item in source_snapshots}
        evaluations = evaluations_by_job.get(job.id, [])
        evaluation = next(
            (
                row
                for row in evaluations
                if row.config_fingerprint == config_fp and row.evaluation_fingerprint in fingerprints
            ),
            None,
        )
        stale = evaluation is None and bool(evaluations)
        if evaluation is None:
            evaluation = evaluations[0] if evaluations else None
        # For display, prefer the latest source snapshot matching this evaluation.
        snapshot = next(
            (item for item in source_snapshots if evaluation and item.fingerprint == evaluation.evaluation_fingerprint),
            source_snapshots[0],
        )
        facts = snapshot.context.facts
        current_review = reviews.get(job.id)
        human_status = (
            HumanReviewStatus(current_review.state)
            if current_review is not None
            else HumanReviewStatus.NEW
        )
        application = applications.get(job.id)
        app_status = ApplicationStatus(application.status) if application is not None else None
        effective_status = human_status
        if application is not None and human_status is HumanReviewStatus.NEW:
            # Any tracked application is not a new recommendation, even if its
            # human review row was never touched.
            effective_status = HumanReviewStatus.SEEN
        if app_status is not None and not include_applied:
            continue
        if status is not None and effective_status is not status:
            continue
        if (
            status is None
            and effective_status is HumanReviewStatus.DISMISSED
            and not include_dismissed
        ):
            continue
        if company_filter is not None and normalize_company_name(job.company.name if job.company else "") != company_filter:
            continue
        if remote_only and facts.remote_policy is not RemotePolicy.REMOTE:
            continue
        if tech_filter and not any(
            tech_filter in item.casefold()
            for item in (*facts.technologies, *facts.required_technologies)
        ):
            continue
        final_decision = (
            FinalDecision(evaluation.decision)
            if evaluation is not None and evaluation.decision is not None and not stale
            else None
        )
        # Project current deterministic gates even when historical semantic
        # evidence is stale. Do not mutate/reuse historical final decisions.
        experience = snapshot.context.deterministic.signals.experience
        if snapshot.context.deterministic.decision is PreFilterDecision.REJECT:
            final_decision = FinalDecision.SKIP
        elif final_decision is FinalDecision.APPLY and experience.outcome is not ExperienceOutcome.MEETS:
            final_decision = FinalDecision.REVIEW
        if (
            decision is None
            and status is None
            and final_decision is FinalDecision.SKIP
            and not include_skip
        ):
            continue
        if decision is not None and final_decision is not decision:
            continue
        answers = evaluation.jev_signals if evaluation and not stale else None
        score = _priority(answers)
        adjustments = _priority_adjustments(snapshot.context) if score is not None else ()
        if score is not None:
            score = min(100, max(0, score + sum(points for points, _label in adjustments)))
        role_relevance = _signal_value(answers, "role_relevance")
        strong_mismatch = _has_strong_mismatch(
            evaluation.deterministic_result if evaluation and not stale else None
        )
        company_name = job.company.name if job.company is not None else snapshot.context.offer.company_name or "Unknown company"
        published = snapshot.context.offer.published_at
        item = Opportunity(
            job_id=job.id,
            evaluation_fingerprint=(
                evaluation.evaluation_fingerprint
                if evaluation is not None and not stale and evaluation.status == EvaluationStatus.EVALUATED.value
                else None
            ),
            title=facts.title,
            company=company_name,
            location=facts.location,
            remote_policy=facts.remote_policy.value if facts.remote_policy else None,
            employment_type=facts.employment_type.value if facts.employment_type else None,
            url=snapshot.context.offer.apply_url or snapshot.context.offer.canonical_url or snapshot.context.offer.source_url,
            technologies=facts.technologies,
            required_technologies=facts.required_technologies,
            salary_min=str(facts.salary_min) if facts.salary_min is not None else None,
            salary_max=str(facts.salary_max) if facts.salary_max is not None else None,
            currency=facts.currency,
            salary_period=facts.salary_period.value if facts.salary_period else None,
            published_at=published,
            decision=final_decision,
            evaluation_status=EvaluationStatus(evaluation.status) if evaluation else None,
            evaluation_is_stale=stale,
            review_state=effective_status,
            application_status=app_status,
            priority=score,
            priority_adjustments=tuple(label for _points, label in adjustments),
            first_seen_at=job.created_at,
            deterministic_result=_prefilter_payload(snapshot.context.deterministic),
            experience=experience,
            jev_signals=answers if isinstance(answers, dict) else None,
            jev_reasons=evaluation.jev_reasons if evaluation and not stale else None,
            company_facts=company_facts(job.company) if job.company is not None else None,
            outreach_recommendation=recommend_outreach(
                final_decision,
                score,
                role_relevance,
                strong_mismatch,
                app_status.value if app_status is not None else None,
                job.id in active_outreach_jobs,
            ),
        )
        decision_rank = {FinalDecision.APPLY: 0, FinalDecision.REVIEW: 1, FinalDecision.SKIP: 2}.get(final_decision, 3)
        output.append((
            (
                decision_rank,
                -(score if score is not None else -1),
                -(published.timestamp() if published else 0.0),
                normalize_company_name(company_name) or "",
                normalize_job_title(facts.title).tokens,
                str(job.id),
            ),
            item,
        ))
    output.sort(key=lambda pair: pair[0])
    return [item for _, item in output[:limit]]


def get_opportunity(session: Session, job_id: UUID, candidate: CandidateConfig) -> Opportunity | None:
    for item in list_opportunities(
        session, candidate, limit=100_000, include_applied=True, include_skip=True
    ):
        if item.job_id == job_id:
            return item
    return None


def set_review_state(
    session: Session,
    job_id: UUID,
    state: HumanReviewStatus,
) -> JobReview:
    """Persist a user review choice without consulting or altering evaluation."""

    _require_clean_session_for_owned_transactions(session)
    with session.begin():
        review = session.scalar(select(JobReview).where(JobReview.job_id == job_id))
        if review is None:
            if session.get(Job, job_id) is None:
                raise OpportunityServiceError(f"Unknown job id: {job_id}.")
            review = JobReview(job_id=job_id, state=state.value)
            session.add(review)
        else:
            review.state = state.value
        session.flush()
        return review


def transition_application(
    session: Session,
    job_id: UUID,
    status: ApplicationStatus,
    *,
    note: str | None = None,
    source: str | None = None,
    application_url: str | None = None,
    cv_version: str | None = None,
) -> Application:
    """Create/update tracked application state and append a status event.

    This records a user-entered status only. It never submits an application.
    """

    _require_clean_session_for_owned_transactions(session)
    cleaned_note = note.strip() if note and note.strip() else None
    if status not in {ApplicationStatus.DRAFT, ApplicationStatus.APPLIED}:
        # A first application record cannot jump directly to an outcome that
        # presupposes a submission.
        existing_id = session.scalar(select(Application.id).where(Application.job_id == job_id))
        session.rollback()
        if existing_id is None:
            raise OpportunityServiceError(
                f"A first application status must be DRAFT or APPLIED, not {status.value}."
            )
    with session.begin():
        if session.get(Job, job_id) is None:
            raise OpportunityServiceError(f"Unknown job id: {job_id}.")
        event_at = datetime.now(UTC)
        application = session.scalar(
            select(Application).where(Application.job_id == job_id).with_for_update()
        )
        if application is None:
            application = Application(
                job_id=job_id,
                status=status.value,
                applied_at=event_at if status is ApplicationStatus.APPLIED else None,
                source=(source.strip() if source and source.strip() else None),
                notes=cleaned_note,
                application_url=(application_url.strip() if application_url and application_url.strip() else None),
                cv_version=(cv_version.strip() if cv_version and cv_version.strip() else None),
            )
            session.add(application)
            session.flush()
            session.add(
                ApplicationEvent(
                    application_id=application.id,
                    event_type="STATUS_CHANGED",
                    from_status=None,
                    to_status=status.value,
                    note=cleaned_note,
                    occurred_at=event_at,
                )
            )
            return application

        current = ApplicationStatus(application.status)
        if source and source.strip():
            application.source = source.strip()
        if cleaned_note is not None:
            application.notes = cleaned_note
        if application_url and application_url.strip():
            application.application_url = application_url.strip()
        if cv_version and cv_version.strip():
            application.cv_version = cv_version.strip()
        if current is status:
            return application  # Repeated CLI command is idempotent.
        if status not in _APPLICATION_TRANSITIONS[current]:
            raise OpportunityServiceError(
                f"Invalid application transition: {current.value} -> {status.value}."
            )
        application.status = status.value
        if status is ApplicationStatus.APPLIED and application.applied_at is None:
            application.applied_at = event_at
        session.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="STATUS_CHANGED",
                from_status=current.value,
                to_status=status.value,
                note=cleaned_note,
                occurred_at=event_at,
            )
        )
        session.flush()
        return application


def _fetch_targets(
    targets: list[CompanyMonitorTarget],
    *,
    max_jobs_per_company: int,
    client: httpx.Client | None,
) -> tuple[list[tuple[NormalizedJob, CompanyMonitorTarget]], list[SourceFailure]]:
    specs: list[JobSourceSpec] = []
    target_by_key: dict[tuple[str, str, str | None], CompanyMonitorTarget] = {}
    for target in targets:
        key = (target.provider.value.casefold(), target.identifier.casefold(), target.region)
        if key in target_by_key:
            continue
        target_by_key[key] = target
        specs.append(
            JobSourceSpec(
                provider=key[0],
                identifier=target.identifier,
                company_name=target.company_name,
                region=target.region,
                max_jobs=max_jobs_per_company,
            )
        )
    if not specs:
        return [], []
    config = JobSourcesConfig(sources=specs)
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(20.0),
        headers={
            "Accept": "application/json",
            "User-Agent": "AI-Job-Hunter/0.1 (personal job discovery)",
        },
    )
    result: list[tuple[NormalizedJob, CompanyMonitorTarget]] = []
    failures: list[SourceFailure] = []
    per_company_counts: dict[UUID, int] = {}
    try:
        connectors = build_job_connectors(config, client=active_client)
        for spec, connector in zip(config.sources, connectors, strict=True):
            target = target_by_key[(spec.provider, spec.identifier.casefold(), spec.region)]
            try:
                fetched = connector.fetch_jobs()
            except (
                AshbyConnectorError,
                GreenhouseConnectorError,
                LeverConnectorError,
                SmartRecruitersConnectorError,
                TeamtailorConnectorError,
            ) as error:
                failures.append(
                    SourceFailure(target.company_name, spec.provider.upper(), type(error).__name__)
                )
                continue
            remaining = max_jobs_per_company - per_company_counts.get(target.company_id, 0)
            accepted = fetched[:max(remaining, 0)]
            per_company_counts[target.company_id] = per_company_counts.get(target.company_id, 0) + len(accepted)
            result.extend((offer, target) for offer in accepted)
    finally:
        if owns_client:
            active_client.close()
    result.sort(key=lambda pair: _offer_order(pair[0], pair[1]))
    return result, failures


def _find_existing_match_fingerprints(
    session: Session,
    offer: NormalizedJob,
    candidate: CandidateConfig,
    engine_identity: str,
) -> tuple[UUID | None, set[str]]:
    """Find the existing canonical job and semantic contexts before ingestion."""

    exact_source = None
    if offer.external_id is not None:
        exact_source = session.scalar(
            select(JobSource).where(
                JobSource.provider == offer.provider,
                JobSource.external_id == offer.external_id,
            )
        )
    if exact_source is not None:
        job = session.scalar(
            select(Job)
            .options(joinedload(Job.company), selectinload(Job.sources))
            .where(Job.id == exact_source.job_id)
        )
        if job is None:
            return None, set()
    else:
        jobs = session.scalars(
            select(Job)
            .options(joinedload(Job.company), selectinload(Job.sources))
            .order_by(Job.id)
        ).unique().all()
        matches = [item for item in (match_job(offer, job) for job in jobs) if item.decision is DeduplicationDecision.MATCH]
        if len(matches) != 1:
            return None, set()
        job = next((item for item in jobs if item.id == matches[0].candidate_job_id), None)
        if job is None:
            return None, set()
    return job.id, {
        item.fingerprint
        for source in sorted(job.sources, key=_source_order)
        if (item := _prepare_from_source(job, source, candidate, engine_identity)) is not None
    }


def _prepare_offer(
    offer: NormalizedJob,
    candidate: CandidateConfig,
    *,
    engine_identity: str,
    job_id: UUID | None = None,
) -> _PreparedOffer:
    canonical_offer = offer.model_copy(
        update={
            "company_name": offer.company_name.strip() if offer.company_name else None,
            "company_website": offer.company_website,
            "raw_metadata": None,
        }
    )
    facts = JobFacts.from_normalized_job(canonical_offer)
    deterministic = evaluate_job(facts, candidate)
    context = JobDecisionContext(
        offer=canonical_offer,
        candidate=candidate,
        facts=facts,
        deterministic=deterministic,
    )
    config_fp = _config_fingerprint(candidate, engine_identity)
    fingerprint = _evaluation_fingerprint(context, job_id, config_fp)
    return _PreparedOffer(canonical_offer, context, fingerprint, config_fp, job_id)


def _prepare_persisted_source(
    session: Session,
    job_id: UUID,
    incoming: NormalizedJob,
    candidate: CandidateConfig,
    engine_identity: str,
) -> _PreparedOffer | None:
    query = (
        select(JobSource)
        .options(
            joinedload(JobSource.job).joinedload(Job.company),
        )
        .where(JobSource.job_id == job_id, JobSource.provider == incoming.provider)
    )
    if incoming.external_id is not None:
        query = query.where(JobSource.external_id == incoming.external_id)
    else:
        urls = [value for value in (incoming.source_url, incoming.canonical_url) if value]
        if not urls:
            return _prepare_offer(incoming, candidate, engine_identity=engine_identity, job_id=job_id)
        query = query.where(
            (JobSource.original_url.in_(urls)) | (JobSource.canonical_url.in_(urls))
        )
    rows = session.scalars(query.order_by(JobSource.id)).all()
    source = rows[0] if rows else None
    if source is None:
        return _prepare_offer(incoming, candidate, engine_identity=engine_identity, job_id=job_id)
    return _prepare_from_source(
        source.job,
        source,
        candidate,
        engine_identity,
        incoming=incoming,
    )


def _prepare_from_source(
    job: Job,
    source: JobSource,
    candidate: CandidateConfig,
    engine_identity: str,
    *,
    incoming: NormalizedJob | None = None,
) -> _PreparedOffer | None:
    title = source.source_title or job.title
    if not title:
        return None
    salary_min = source.salary_min
    salary_max = source.salary_max
    if incoming is not None:
        if _same_numeric_value(incoming.salary_min, source.salary_min):
            salary_min = incoming.salary_min
        if _same_numeric_value(incoming.salary_max, source.salary_max):
            salary_max = incoming.salary_max
    offer = NormalizedJob(
        provider=source.provider,
        external_id=source.external_id,
        source_url=source.original_url,
        canonical_url=source.canonical_url,
        apply_url=source.apply_url,
        title=title,
        company_name=job.company.name if job.company is not None else None,
        company_website=source.company_website or (job.company.website_url if job.company else None),
        description=source.source_description,
        location=source.source_location,
        remote_policy=_enum_or_none(RemotePolicy, source.remote_policy),
        remote_eligibility=_enum_or_default(RemoteEligibility, source.remote_eligibility, RemoteEligibility.UNKNOWN),
        salary_min=salary_min,
        salary_max=salary_max,
        currency=source.salary_currency,
        salary_period=_enum_or_none(SalaryPeriod, source.salary_period),
        employment_type=_enum_or_none(EmploymentType, source.employment_type),
        published_at=_as_utc(source.published_at),
        discovered_at=_as_utc(source.discovered_at),
        raw_metadata=None,
    )
    return _prepare_offer(offer, candidate, engine_identity=engine_identity, job_id=job.id)


def _same_numeric_value(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (ValueError, TypeError, ArithmeticError):
        return False


def _evaluation_fingerprint(
    context: JobDecisionContext,
    job_id: UUID | None,
    config_fingerprint: str,
) -> str:
    offer = context.offer
    facts = context.facts
    payload = {
        "job_id": str(job_id) if job_id is not None else None,
        "config_fingerprint": config_fingerprint,
        "job": {
            "title": offer.title,
            "company": offer.company_name,
            "company_website": offer.company_website,
            "location": offer.location,
            "remote_policy": offer.remote_policy.value if offer.remote_policy else None,
            "remote_eligibility": offer.remote_eligibility.value,
            "employment_type": offer.employment_type.value if offer.employment_type else None,
            "description": offer.description,
            "salary_min": _canonical_decimal(offer.salary_min),
            "salary_max": _canonical_decimal(offer.salary_max),
            "currency": offer.currency,
            "salary_period": offer.salary_period.value if offer.salary_period else None,
        },
        "facts": {
            "inferred_seniority": facts.inferred_seniority.value,
            "technologies": facts.technologies,
            "required_technologies": facts.required_technologies,
        },
        "prefilter": {
            "decision": context.deterministic.decision.value,
            # Provider Decimals can arrive as 40000 or 40000.00. Database
            # Numeric columns normalize scale, so normalize numbers embedded
            # in explanatory strings before hashing to keep round-trips stable.
            "reasons": [
                _canonicalize_reason_numbers(reason)
                for reason in context.deterministic.reasons
            ],
        },
    }
    return _hash_payload(payload)


def _canonicalize_reason_numbers(reason: str) -> str:
    return _REASON_NUMBER.sub(
        lambda match: _canonical_decimal(Decimal(match.group())) or match.group(),
        reason,
    )


def _canonical_decimal(value: Any) -> str | None:
    if value is None:
        return None
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return str(value)
    if not decimal_value.is_finite():
        return str(value)
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _config_fingerprint(candidate: CandidateConfig, engine_identity: str) -> str:
    return _hash_payload(
        {
            "candidate": candidate.model_dump(mode="json"),
            "prefilter_version": _PREFILTER_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "rubric": RUBRIC_SPEC,
            "policy_version": POLICY_VERSION_V2,
            "engine_identity": engine_identity,
        }
    )


def _persist_evaluation(
    session: Session,
    prepared: _PreparedOffer,
    result: JobDecisionResult,
    *,
    engine_name: str,
) -> JobEvaluation:
    _require_clean_session_for_owned_transactions(session)
    with session.begin():
        evaluation = session.scalar(
            select(JobEvaluation).where(
                JobEvaluation.job_id == _required_job_id(prepared),
                JobEvaluation.evaluation_fingerprint == prepared.fingerprint,
            )
        )
        if evaluation is None:
            evaluation = JobEvaluation(
                job_id=_required_job_id(prepared),
                evaluation_fingerprint=prepared.fingerprint,
                rubric_version=RUBRIC_VERSION,
                policy_version=POLICY_VERSION_V2,
                engine_name=engine_name,
                config_fingerprint=prepared.config_fingerprint,
                deterministic_result={},
            )
            session.add(evaluation)
        evaluation.status = EvaluationStatus.EVALUATED.value
        evaluation.decision = result.final_decision.value
        evaluation.rubric_version = result.rubric_version
        evaluation.policy_version = result.policy_version
        evaluation.engine_name = engine_name
        evaluation.engine_configuration = _safe_engine_configuration(result.engine_configuration)
        evaluation.model_version = result.model_version
        evaluation.config_fingerprint = prepared.config_fingerprint
        evaluation.deterministic_result = _prefilter_payload(prepared.context.deterministic)
        evaluation.jev_signals = (
            result.jev_answers.model_dump(mode="json") if result.jev_answers is not None else None
        )
        evaluation.jev_reasons = {
            "reasons": list(result.reasons),
            "review_reasons": [item.model_dump(mode="json") for item in result.review_reasons],
        }
        evaluation.evaluated_at = result.evaluated_at
        session.flush()
        return evaluation


def _persist_pending(
    session: Session,
    prepared: _PreparedOffer,
    engine_identity: str,
    reason: str,
    *,
    budget_limit: int | None = None,
) -> JobEvaluation:
    _require_clean_session_for_owned_transactions(session)
    with session.begin():
        evaluation = session.scalar(
            select(JobEvaluation).where(
                JobEvaluation.job_id == _required_job_id(prepared),
                JobEvaluation.evaluation_fingerprint == prepared.fingerprint,
            )
        )
        if evaluation is None:
            evaluation = JobEvaluation(
                job_id=_required_job_id(prepared),
                evaluation_fingerprint=prepared.fingerprint,
                rubric_version=RUBRIC_VERSION,
                policy_version=POLICY_VERSION_V2,
                engine_name=_ENGINE_NAME,
                engine_configuration=_safe_engine_configuration(engine_identity),
                config_fingerprint=prepared.config_fingerprint,
                deterministic_result={},
            )
            session.add(evaluation)
        evaluation.status = EvaluationStatus.PENDING.value
        evaluation.decision = None
        evaluation.rubric_version = RUBRIC_VERSION
        evaluation.policy_version = POLICY_VERSION_V2
        evaluation.engine_name = _ENGINE_NAME
        evaluation.engine_configuration = _safe_engine_configuration(engine_identity)
        evaluation.model_version = None
        evaluation.config_fingerprint = prepared.config_fingerprint
        evaluation.deterministic_result = _prefilter_payload(prepared.context.deterministic)
        evaluation.jev_signals = None
        evaluation.jev_reasons = {"pending_reason": reason}
        if budget_limit is not None:
            evaluation.jev_reasons["pending_budget_limit"] = budget_limit
        evaluation.evaluated_at = None
        session.flush()
        return evaluation


def _ensure_review_row(session: Session, job_id: UUID) -> None:
    _require_clean_session_for_owned_transactions(session)
    try:
        with session.begin():
            exists = session.scalar(select(JobReview.id).where(JobReview.job_id == job_id))
            if exists is None:
                session.add(JobReview(job_id=job_id, state=HumanReviewStatus.NEW.value))
    except IntegrityError:
        # A concurrent refresh may have created the one-per-job row.
        session.rollback()


def _evaluation_for_fingerprint(
    session: Session,
    prepared: _PreparedOffer,
) -> tuple[str, str | None, dict[str, Any] | list[Any] | None] | None:
    if prepared.job_id is None:
        return None
    row = session.execute(
        select(JobEvaluation.status, JobEvaluation.decision, JobEvaluation.jev_reasons).where(
            JobEvaluation.job_id == prepared.job_id,
            JobEvaluation.evaluation_fingerprint == prepared.fingerprint,
        )
    ).one_or_none()
    if row is None:
        return None
    return row.status, row.decision, row.jev_reasons


def _evaluate_hard_skip(context: JobDecisionContext, engine_identity: str) -> JobDecisionResult:
    from ai_job_hunter.decision_engine import DeterministicDecisionSummary

    return JobDecisionResult(
        final_decision=FinalDecision.SKIP,
        reasons=context.deterministic.reasons,
        jev_answers=None,
        deterministic_result=DeterministicDecisionSummary(
            prefilter_decision=context.deterministic.decision,
            reasons=context.deterministic.reasons,
        ),
        model_version=None,
        engine_configuration=engine_identity,
        rubric_version=RUBRIC_VERSION,
        policy_version=POLICY_VERSION_V2,
        evaluated_at=datetime.now(UTC),
    )


def _source_context_fingerprints(
    job: Job,
    candidate: CandidateConfig,
    engine_identity: str,
) -> list[_PreparedOffer]:
    return [
        item
        for source in sorted(job.sources, key=_source_order)
        if (item := _prepare_from_source(job, source, candidate, engine_identity)) is not None
    ]


def _offer_order(offer: NormalizedJob, target: CompanyMonitorTarget | None) -> tuple[Any, ...]:
    return (
        normalize_company_name(target.company_name if target else offer.company_name) or "",
        offer.provider.casefold(),
        offer.published_at.timestamp() * -1 if offer.published_at else 0.0,
        normalize_job_title(offer.title).tokens,
        offer.external_id or "",
        offer.canonical_url or offer.source_url or "",
    )


def _evaluation_order(item: _PreparedOffer) -> tuple[Any, ...]:
    offer = item.offer
    prefilter_rank = 0 if item.context.deterministic.decision is PreFilterDecision.PASS else 1
    published = offer.published_at.timestamp() if offer.published_at else 0.0
    return (
        prefilter_rank,
        -published,
        normalize_company_name(offer.company_name) or "",
        normalize_job_title(offer.title).tokens,
        str(item.context.offer.external_id or ""),
        item.fingerprint,
    )


RELOCATION_PENALTY = 15
_REMOTE_LOCATION_TEXT = re.compile(r"\b(?:remote|remoto|remota|anywhere|worldwide)\b", re.IGNORECASE)


SALARY_BONUS_AT_TARGET = 5
SALARY_BONUS_HIGH = 10


def _priority_adjustments(context: JobDecisionContext) -> tuple[tuple[int, str], ...]:
    """Soft preferences that change review order (never eligibility)."""

    return _relocation_adjustment(context) + _salary_adjustment(context)


def _relocation_adjustment(context: JobDecisionContext) -> tuple[tuple[int, str], ...]:
    """Relocation is acceptable but much less attractive than the preferred locations.

    An on-site or hybrid role (or an unknown work mode in a named city) outside
    the preferred locations loses RELOCATION_PENALTY points.
    """

    offer = context.offer
    preferred = context.deterministic.signals.preferred_location.status
    if offer.remote_policy is RemotePolicy.REMOTE or preferred is SignalStatus.COMPATIBLE:
        return ()
    if not context.candidate.preferences.preferred_locations:
        return ()
    if offer.remote_policy is None and (not offer.location or _REMOTE_LOCATION_TEXT.search(offer.location)):
        return ()
    places = ", ".join(context.candidate.preferences.preferred_locations)
    return ((-RELOCATION_PENALTY, f"fuera de {places}, requiere mudanza (−{RELOCATION_PENALTY})"),)


def _salary_adjustment(context: JobDecisionContext) -> tuple[tuple[int, str], ...]:
    """A published salary at or above the target moves a job up; no currency conversion."""

    preferences = context.candidate.preferences
    facts = context.facts
    target = preferences.target_salary
    currency = (preferences.salary_currency or "").upper()
    if target is None or not currency or (facts.currency or "").upper() != currency:
        return ()
    yearly = {SalaryPeriod.YEAR: Decimal(1), SalaryPeriod.MONTH: Decimal(12)}.get(facts.salary_period)
    published = facts.salary_max or facts.salary_min
    if yearly is None or published is None:
        return ()
    annual = Decimal(str(published)) * yearly
    if annual >= Decimal(str(target)) * 2:
        return ((SALARY_BONUS_HIGH, f"salario alto publicado (+{SALARY_BONUS_HIGH})"),)
    if annual >= Decimal(str(target)):
        return ((SALARY_BONUS_AT_TARGET, f"salario publicado ≥ objetivo (+{SALARY_BONUS_AT_TARGET})"),)
    return ()


def _priority(signals: dict[str, Any] | None) -> int | None:
    """Equal-weight mean of six Jev fit signals, scaled to 0..100; never probability."""
    if not isinstance(signals, dict):
        return None
    names = (
        "role_relevance",
        "backend_relevance",
        "stack_transferability",
        "experience_accessibility",
        "requirements_flexibility",
        "career_value",
    )
    values: list[float] = []
    for name in names:
        signal = signals.get(name)
        value = signal.get("value") if isinstance(signal, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        values.append(float(value))
    return round(sum(values) / len(values) * 100)


def _signal_value(signals: dict[str, Any] | None, name: str) -> float | None:
    if not isinstance(signals, dict):
        return None
    item = signals.get(name)
    value = item.get("value") if isinstance(item, dict) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)


def _has_strong_mismatch(deterministic_result: dict[str, Any] | None) -> bool:
    if not isinstance(deterministic_result, dict):
        return False
    signals = deterministic_result.get("signals")
    technology = signals.get("technology") if isinstance(signals, dict) else None
    mismatches = technology.get("critical_mismatches") if isinstance(technology, dict) else None
    return isinstance(mismatches, (list, tuple)) and bool(mismatches)


def _prefilter_payload(result: JobPreFilterResult) -> dict[str, Any]:
    signals = result.signals
    return {
        "decision": result.decision.value,
        "reasons": list(result.reasons),
        "signals": {
            "geography": {"status": signals.geography.status.value, "reason": signals.geography.reason},
            "salary": {"evaluation": signals.salary.evaluation.value, "reason": signals.salary.reason},
            "seniority": {"status": signals.seniority.status.value, "reason": signals.seniority.reason},
            "experience": {
                "outcome": signals.experience.outcome.value,
                "requirements": signals.experience.requirement_display,
                "reason": signals.experience.reason,
                "shortfall_years": _canonical_decimal(signals.experience.shortfall_years),
                "evidence": list(signals.experience.evidence),
            },
            "employment_type": {"status": signals.employment_type.status.value, "reason": signals.employment_type.reason},
            "remote_preference": {"status": signals.remote_preference.status.value, "reason": signals.remote_preference.reason},
            "preferred_role": {"status": signals.preferred_role.status.value, "reason": signals.preferred_role.reason},
            "role_family": {
                "fit": signals.role_family.fit.value,
                "family": signals.role_family.family,
                "reason": signals.role_family.reason,
            },
            "preferred_location": {"status": signals.preferred_location.status.value, "reason": signals.preferred_location.reason},
            "technology": {
                "matching_primary_skills": list(signals.technology.matching_primary_skills),
                "matching_secondary_skills": list(signals.technology.matching_secondary_skills),
                "matching_candidate_technologies": list(signals.technology.matching_candidate_technologies),
                "matching_preferred_technologies": list(signals.technology.matching_preferred_technologies),
                "missing_technologies": list(signals.technology.missing_technologies),
                "learnable_technologies": list(signals.technology.learnable_technologies),
                "transferable_technologies": list(signals.technology.transferable_technologies),
                "critical_mismatches": list(signals.technology.critical_mismatches),
            },
        },
    }


def _count_decision(summary: RefreshSummary, decision: str | None) -> None:
    if decision == FinalDecision.APPLY.value:
        summary.apply += 1
    elif decision == FinalDecision.REVIEW.value:
        summary.review += 1
    elif decision == FinalDecision.SKIP.value:
        summary.skip += 1


def _source_order(source: JobSource) -> tuple[Any, ...]:
    discovered = _as_utc(source.discovered_at) or datetime.min.replace(tzinfo=UTC)
    return (discovered.timestamp(), source.provider.casefold(), source.external_id or "", str(source.id))


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite may return timezone-aware columns as naive; persisted values are UTC."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _engine_identity(engine: JobDecisionEngine | None) -> str:
    if engine is None:
        return JevJobDecisionEngine().cache_identity
    return engine.cache_identity


def _safe_engine_configuration(value: str | None) -> str | None:
    if value is None:
        return None
    lowered = value.casefold()
    if "api_key" in lowered or "apikey" in lowered or "token=" in lowered:
        return "redacted-engine-configuration"
    return value[:255]


def _enum_or_none(enum_type: type[StrEnum], value: Any) -> Any | None:
    if value is None:
        return None
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return None


def _enum_or_default(enum_type: type[StrEnum], value: Any, default: StrEnum) -> Any:
    return _enum_or_none(enum_type, value) or default


def _hash_payload(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _required_job_id(prepared: _PreparedOffer) -> UUID:
    job_id = prepared.job_id
    if not isinstance(job_id, UUID):
        raise OpportunityServiceError("Internal evaluation is missing its persisted job id.")
    return job_id


def _require_clean_session_for_owned_transactions(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        raise OpportunityServiceError("Use a clean Session with no pending writes for this operation.")
    if session.in_transaction():
        # Service entrypoints own their write transactions. Ending a read-only
        # autobegin transaction is safe; pending writes are rejected above.
        session.rollback()
    if session.in_transaction():
        # Service entrypoints own their write transactions. Ending a read-only
        # autobegin transaction is safe; pending writes are rejected above.
        session.rollback()
