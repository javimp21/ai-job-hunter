"""Transactional persistence for normalized job offers."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource


class IngestionStatus(StrEnum):
    """Outcome of ingesting one normalized offer."""

    CREATED = "created"
    ALREADY_KNOWN = "already_known"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Identifiers and status returned after a successful ingestion."""

    status: IngestionStatus
    job_id: UUID
    job_source_id: UUID
    company_id: UUID | None
    refreshed: bool = False


def ingest_job(session: Session, offer: NormalizedJob) -> IngestionResult:
    """Create a job occurrence or refresh it when its provider ID already exists.

    This function owns one transaction and expects a session with no active
    transaction. Repeated identified offers update the existing source snapshot
    while preserving its first ``discovered_at`` value.
    """

    with session.begin():
        company = _find_or_create_company(session, offer)
        existing_source = _find_source(session, offer)

        if existing_source is not None:
            job = existing_source.job
            if company is not None:
                job.company = company
            _refresh_job(job, offer)
            _refresh_source(existing_source, offer)
            session.flush()
            return IngestionResult(
                status=IngestionStatus.ALREADY_KNOWN,
                job_id=job.id,
                job_source_id=existing_source.id,
                company_id=job.company_id,
                refreshed=True,
            )

        job = Job(
            company=company,
            title=offer.title,
            description=offer.description,
            location=offer.location,
            remote_policy=offer.remote_policy.value if offer.remote_policy else None,
        )
        source = JobSource(job=job)
        _refresh_source(source, offer)
        session.add(job)
        session.flush()
        return IngestionResult(
            status=IngestionStatus.CREATED,
            job_id=job.id,
            job_source_id=source.id,
            company_id=job.company_id,
        )


def _find_or_create_company(session: Session, offer: NormalizedJob) -> Company | None:
    if offer.company_name is None:
        return None

    company = session.scalar(
        select(Company)
        .where(func.lower(Company.name) == offer.company_name.lower())
        .limit(1)
    )
    if company is None:
        company = Company(name=offer.company_name, website_url=offer.company_website)
        session.add(company)
    elif company.website_url is None and offer.company_website is not None:
        company.website_url = offer.company_website
    return company


def _find_source(session: Session, offer: NormalizedJob) -> JobSource | None:
    if offer.external_id is None:
        return None
    return session.scalar(
        select(JobSource).where(
            JobSource.provider == offer.provider,
            JobSource.external_id == offer.external_id,
        )
    )


def _refresh_job(job: Job, offer: NormalizedJob) -> None:
    job.title = offer.title
    if offer.description is not None:
        job.description = offer.description
    if offer.location is not None:
        job.location = offer.location
    if offer.remote_policy is not None:
        job.remote_policy = offer.remote_policy.value


def _refresh_source(source: JobSource, offer: NormalizedJob) -> None:
    source.provider = offer.provider
    source.external_id = offer.external_id
    source.original_url = offer.source_url
    source.raw_metadata = offer.raw_metadata
    source.salary_min = offer.salary_min
    source.salary_max = offer.salary_max
    source.salary_currency = offer.currency
    source.salary_period = offer.salary_period.value if offer.salary_period else None
    source.employment_type = offer.employment_type.value if offer.employment_type else None
    source.remote_policy = offer.remote_policy.value if offer.remote_policy else None
    source.remote_eligibility = offer.remote_eligibility.value
    source.published_at = offer.published_at
    if source.id is None:
        source.discovered_at = offer.discovered_at
