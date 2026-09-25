from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource
from ai_job_hunter.services.ingestion import IngestionStatus, ingest_job


def test_ingestion_creates_company_job_and_source(db_session, fake_offer_batch) -> None:
    offer = fake_offer_batch[0]

    result = ingest_job(db_session, offer)

    assert result.status is IngestionStatus.CREATED
    assert result.refreshed is False
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1

    job = db_session.get(Job, result.job_id)
    source = db_session.get(JobSource, result.job_source_id)
    assert job is not None and job.company_id == result.company_id
    assert source is not None and source.job_id == result.job_id
    assert source.original_url == offer.source_url
    assert source.salary_min == Decimal("60000.00")
    assert source.salary_currency == "EUR"
    assert source.remote_policy == "HYBRID"
    assert source.remote_eligibility == "SPAIN_ONLY"
    assert source.published_at.replace(tzinfo=UTC) == offer.published_at


def test_repeated_provider_id_refreshes_existing_source_and_reuses_company(
    db_session, fake_offer_batch
) -> None:
    original, _, refreshed = fake_offer_batch

    first = ingest_job(db_session, original)
    second = ingest_job(db_session, refreshed)

    assert first.status is IngestionStatus.CREATED
    assert second.status is IngestionStatus.ALREADY_KNOWN
    assert second.refreshed is True
    assert second.job_id == first.job_id
    assert second.job_source_id == first.job_source_id
    assert second.company_id == first.company_id
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1

    job = db_session.get(Job, first.job_id)
    source = db_session.get(JobSource, first.job_source_id)
    # A known source can refresh its own snapshot, but canonical fields are
    # only completed when missing; later source data cannot overwrite them.
    assert job is not None and job.title == "Platform Engineer"
    assert job.description == "Build platform services."
    assert source is not None
    assert source.salary_min == Decimal("70000.00")
    assert source.salary_max == Decimal("85000.00")
    assert source.raw_metadata == {"team": "Platform", "level": "Senior"}
    assert source.discovered_at.replace(tzinfo=UTC) == original.discovered_at


def test_missing_external_id_never_auto_merges_without_strong_url(db_session) -> None:
    offer = NormalizedJob(
        provider="example-board",
        external_id=None,
        source_url="https://jobs.example.test/open-role",
        title="Open role",
        company_name="Example Company",
        discovered_at=datetime(2026, 9, 24, tzinfo=UTC),
    )

    first = ingest_job(db_session, offer)
    second = ingest_job(db_session, offer)

    assert first.status is IngestionStatus.CREATED
    assert second.status is IngestionStatus.POSSIBLE_MATCH
    assert first.job_id != second.job_id
    assert first.job_source_id != second.job_source_id
    assert len(second.possible_matches) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 2
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1


def test_missing_external_id_refreshes_unique_provider_job_url_in_place(db_session) -> None:
    original = NormalizedJob(
        provider="example-board",
        external_id=None,
        source_url="https://jobs.example.test/roles/123",
        canonical_url="https://jobs.example.test/roles/123",
        title="Backend Engineer",
        company_name="Example Company",
        description="Original role description",
        discovered_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    updated = original.model_copy(
        update={"description": "Updated role description", "discovered_at": datetime(2026, 9, 25, tzinfo=UTC)}
    )

    first = ingest_job(db_session, original)
    second = ingest_job(db_session, updated)

    assert first.status is IngestionStatus.CREATED
    assert second.status is IngestionStatus.ALREADY_KNOWN
    assert second.job_id == first.job_id
    assert second.job_source_id == first.job_source_id
    assert second.materially_changed is True
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1
    source = db_session.get(JobSource, first.job_source_id)
    assert source is not None
    assert source.external_id is None
    assert source.source_description == "Updated role description"
