"""Transactional persistence for normalized job offers."""

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_hunter.deduplication.matcher import (
    DeduplicationDecision,
    DeduplicationResult,
    match_job,
)
from ai_job_hunter.deduplication.normalization import (
    extract_company_domain,
    normalize_company_name,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource


class IngestionStatus(StrEnum):
    """Outcome of ingesting one normalized offer."""

    CREATED = "created"
    ALREADY_KNOWN = "already_known"
    MATCHED_EXISTING = "matched_existing"
    POSSIBLE_MATCH = "possible_match"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Identifiers and status returned after a successful ingestion."""

    status: IngestionStatus
    job_id: UUID
    job_source_id: UUID
    company_id: UUID | None
    refreshed: bool = False
    deduplication: DeduplicationResult | None = None
    possible_matches: tuple[DeduplicationResult, ...] = ()


def ingest_job(session: Session, offer: NormalizedJob) -> IngestionResult:
    """Create a job occurrence or refresh it when its provider ID already exists.

    This function owns one transaction and expects a session with no active
    transaction. Exact provider IDs take precedence. Without one, only a shared
    job-specific URL can merge an offer; weaker evidence is returned for review.
    """

    with session.begin():
        existing_source = _find_source(session, offer)

        if existing_source is not None:
            job = existing_source.job
            _complete_company_if_missing(session, job, offer)
            _fill_missing_canonical_fields(job, offer)
            _refresh_source(existing_source, offer, is_new=False)
            session.flush()
            return IngestionResult(
                status=IngestionStatus.ALREADY_KNOWN,
                job_id=job.id,
                job_source_id=existing_source.id,
                company_id=job.company_id,
                refreshed=True,
            )

        candidates = _find_plausible_candidates(session, offer)
        strong_matches = [
            result for result in candidates if result.decision is DeduplicationDecision.MATCH
        ]
        possible_matches = [
            result for result in candidates if result.decision is DeduplicationDecision.POSSIBLE_MATCH
        ]

        if len(strong_matches) == 1:
            match = strong_matches[0]
            job = session.get(Job, match.candidate_job_id)
            if job is None:
                raise RuntimeError("matched job disappeared during ingestion")
            _complete_company_if_missing(session, job, offer)
            _fill_missing_canonical_fields(job, offer)
            source = JobSource(job=job)
            _refresh_source(source, offer, is_new=True)
            session.add(source)
            session.flush()
            return IngestionResult(
                status=IngestionStatus.MATCHED_EXISTING,
                job_id=job.id,
                job_source_id=source.id,
                company_id=job.company_id,
                deduplication=match,
                possible_matches=tuple(possible_matches),
            )

        if len(strong_matches) > 1:
            possible_matches.extend(
                replace(
                    match,
                    decision=DeduplicationDecision.POSSIBLE_MATCH,
                    reasons=match.reasons
                    + ("multiple existing jobs share this strong URL; automatic merge is ambiguous",),
                )
                for match in strong_matches
            )

        company = _find_or_create_company(session, offer)
        job = Job(
            company=company,
            title=offer.title,
            description=offer.description,
            location=offer.location,
            remote_policy=offer.remote_policy.value if offer.remote_policy else None,
        )
        source = JobSource(job=job)
        _refresh_source(source, offer, is_new=True)
        session.add(job)
        session.flush()
        return IngestionResult(
            status=(
                IngestionStatus.POSSIBLE_MATCH
                if possible_matches
                else IngestionStatus.CREATED
            ),
            job_id=job.id,
            job_source_id=source.id,
            company_id=job.company_id,
            possible_matches=tuple(sorted(possible_matches, key=lambda item: str(item.candidate_job_id))),
        )


def _find_or_create_company(session: Session, offer: NormalizedJob) -> Company | None:
    if offer.company_name is None:
        return None

    name_key = normalize_company_name(offer.company_name)
    domain = extract_company_domain(offer.company_website)
    companies = session.scalars(select(Company).order_by(Company.id)).all()
    domains = {
        company.id: extract_company_domain(company.website_url)
        for company in companies
    }

    if domain is not None:
        same_domain = [company for company in companies if domains[company.id] == domain]
        if len(same_domain) == 1:
            return _enrich_company(same_domain[0], offer)
        if len(same_domain) > 1 and name_key is not None:
            named_matches = [
                company
                for company in same_domain
                if normalize_company_name(company.name) == name_key
            ]
            if len(named_matches) == 1:
                return _enrich_company(named_matches[0], offer)

    same_name = [
        company
        for company in companies
        if name_key is not None and normalize_company_name(company.name) == name_key
    ]
    compatible_name_matches = [
        company
        for company in same_name
        if domain is None or domains[company.id] is None or domains[company.id] == domain
    ]
    if len(compatible_name_matches) == 1:
        return _enrich_company(compatible_name_matches[0], offer)
    if len(same_name) > 1 or (same_name and not compatible_name_matches):
        # Ambiguous or contradictory identity: leave companies separate.
        company = Company(name=offer.company_name, website_url=offer.company_website)
        session.add(company)
        return company

    company = Company(name=offer.company_name, website_url=offer.company_website)
    session.add(company)
    return company


def _enrich_company(company: Company, offer: NormalizedJob) -> Company:
    if company.website_url is None and offer.company_website is not None:
        company.website_url = offer.company_website
    return company


def _complete_company_if_missing(session: Session, job: Job, offer: NormalizedJob) -> None:
    if job.company is None:
        job.company = _find_or_create_company(session, offer)
        return

    company = job.company
    same_name = normalize_company_name(company.name) == normalize_company_name(offer.company_name)
    same_domain = (
        extract_company_domain(company.website_url) is not None
        and extract_company_domain(company.website_url) == extract_company_domain(offer.company_website)
    )
    if (same_name or same_domain) and company.website_url is None:
        _enrich_company(company, offer)


def _fill_missing_canonical_fields(job: Job, offer: NormalizedJob) -> None:
    """Keep the first non-empty canonical value; later sources only fill gaps."""

    if not job.description and offer.description:
        job.description = offer.description
    if not job.location and offer.location:
        job.location = offer.location
    if not job.remote_policy and offer.remote_policy is not None:
        job.remote_policy = offer.remote_policy.value


def _find_plausible_candidates(session: Session, offer: NormalizedJob) -> list[DeduplicationResult]:
    jobs = session.scalars(
        select(Job)
        .options(joinedload(Job.company), selectinload(Job.sources))
        .order_by(Job.id)
    ).unique().all()
    results = [match_job(offer, candidate) for candidate in jobs]
    return [
        result
        for result in results
        if result.decision is not DeduplicationDecision.NO_MATCH
    ]


def _find_source(session: Session, offer: NormalizedJob) -> JobSource | None:
    if offer.external_id is None:
        return None
    return session.scalar(
        select(JobSource).where(
            JobSource.provider == offer.provider,
            JobSource.external_id == offer.external_id,
        )
    )


def _refresh_source(source: JobSource, offer: NormalizedJob, *, is_new: bool) -> None:
    source.provider = offer.provider
    source.external_id = offer.external_id
    if offer.source_url is not None:
        source.original_url = offer.source_url
    if offer.canonical_url is not None:
        source.canonical_url = offer.canonical_url
    if offer.apply_url is not None:
        source.apply_url = offer.apply_url
    if offer.company_website is not None:
        source.company_website = offer.company_website
    if offer.raw_metadata is not None:
        source.raw_metadata = offer.raw_metadata
    if offer.salary_min is not None:
        source.salary_min = offer.salary_min
    if offer.salary_max is not None:
        source.salary_max = offer.salary_max
    if offer.currency is not None:
        source.salary_currency = offer.currency
    if offer.salary_period is not None:
        source.salary_period = offer.salary_period.value
    if offer.employment_type is not None:
        source.employment_type = offer.employment_type.value
    if offer.remote_policy is not None:
        source.remote_policy = offer.remote_policy.value
    if is_new or offer.remote_eligibility.value != "UNKNOWN":
        source.remote_eligibility = offer.remote_eligibility.value
    if offer.published_at is not None:
        source.published_at = offer.published_at
    if is_new:
        source.discovered_at = offer.discovered_at
