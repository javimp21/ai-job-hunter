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
    is_job_specific_url,
    normalize_company_name,
    normalize_job_url,
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
    materially_changed: bool = False
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
            previous_inputs = _source_material_inputs(existing_source)
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
                materially_changed=previous_inputs != _offer_material_inputs(offer),
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
                materially_changed=True,
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
            materially_changed=True,
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
        exact_source = None
    else:
        exact_source = session.scalar(
            select(JobSource).where(
                JobSource.provider == offer.provider,
                JobSource.external_id == offer.external_id,
            )
        )
    if exact_source is not None:
        return exact_source

    incoming_urls = {
        normalized
        for value in (offer.canonical_url, offer.source_url, offer.apply_url)
        if is_job_specific_url(value) and (normalized := normalize_job_url(value))
    }
    if not incoming_urls:
        return None

    # Some ATS records have no stable external identifier. A unique, exact
    # provider-owned job URL still identifies that source snapshot and makes
    # repeated fetches idempotent without merging separate canonical jobs.
    sources = session.scalars(
        select(JobSource)
        .where(JobSource.provider == offer.provider)
        .order_by(JobSource.id)
    ).all()
    matches = [
        source
        for source in sources
        if incoming_urls
        & {
            normalized
            for value in (source.canonical_url, source.original_url, source.apply_url)
            if is_job_specific_url(value) and (normalized := normalize_job_url(value))
        }
    ]
    # Older runs may already have produced multiple rows for one canonical
    # job. Reuse its oldest source row when the URL points to only one Job;
    # refuse to choose if the same provider URL is attached to distinct Jobs.
    if matches and len({source.job_id for source in matches}) == 1:
        return matches[0]
    return None


def _refresh_source(source: JobSource, offer: NormalizedJob, *, is_new: bool) -> None:
    source.provider = offer.provider
    if offer.external_id is not None:
        source.external_id = offer.external_id
    if offer.source_url is not None:
        source.original_url = offer.source_url
    if offer.canonical_url is not None:
        source.canonical_url = offer.canonical_url
    if offer.apply_url is not None:
        source.apply_url = offer.apply_url
    if offer.company_website is not None:
        source.company_website = offer.company_website
    # These fields describe the current provider snapshot, so missing values
    # must clear stale values when an existing posting changes.
    source.source_title = offer.title
    source.source_description = offer.description
    source.source_location = offer.location
    if offer.raw_metadata is not None:
        source.raw_metadata = offer.raw_metadata
    source.salary_min = offer.salary_min
    source.salary_max = offer.salary_max
    source.salary_currency = offer.currency
    source.salary_period = offer.salary_period.value if offer.salary_period else None
    source.employment_type = offer.employment_type.value if offer.employment_type else None
    source.remote_policy = offer.remote_policy.value if offer.remote_policy else None
    source.remote_eligibility = offer.remote_eligibility.value
    source.published_at = offer.published_at
    if is_new:
        source.discovered_at = offer.discovered_at
    source.last_seen_at = offer.discovered_at
    source.closed_at = None  # listed again, so not (or no longer) closed


def _offer_material_inputs(offer: NormalizedJob) -> tuple[object, ...]:
    """Return only provider-supplied facts that can change deterministic/Jev input."""

    return (
        offer.title,
        offer.description,
        offer.location,
        offer.remote_policy.value if offer.remote_policy else None,
        offer.remote_eligibility.value,
        str(offer.salary_min) if offer.salary_min is not None else None,
        str(offer.salary_max) if offer.salary_max is not None else None,
        offer.currency,
        offer.salary_period.value if offer.salary_period else None,
        offer.employment_type.value if offer.employment_type else None,
    )


def _source_material_inputs(source: JobSource) -> tuple[object, ...]:
    """Match the normalized provider facts retained for an existing source."""

    return (
        source.source_title or source.job.title,
        source.source_description,
        source.source_location,
        source.remote_policy,
        source.remote_eligibility,
        str(source.salary_min) if source.salary_min is not None else None,
        str(source.salary_max) if source.salary_max is not None else None,
        source.salary_currency,
        source.salary_period,
        source.employment_type,
    )
