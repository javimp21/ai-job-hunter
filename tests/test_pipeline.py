from sqlalchemy import event, func, select

from ai_job_hunter.connectors import FakeJobConnector
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource
from ai_job_hunter.services.pipeline import run_ingestion_pipeline


def test_pipeline_summary_ingests_fake_batch_and_reuses_company(
    db_session, fake_offer_batch
) -> None:
    summary = run_ingestion_pipeline(FakeJobConnector(fake_offer_batch), db_session)

    assert (summary.fetched, summary.created, summary.already_known, summary.failed) == (3, 2, 1, 0)
    assert summary.failures == []
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 2


def test_pipeline_rolls_back_failed_offer_and_continues(db_session) -> None:
    offers = (
        NormalizedJob(
            provider="fake",
            external_id="bad-offer",
            title="Offer that fails",
            company_name="Company to roll back",
        ),
        NormalizedJob(
            provider="fake",
            external_id="good-offer",
            title="Offer that succeeds",
            company_name="Company that persists",
        ),
    )

    def fail_first_source(mapper, connection, source) -> None:
        if source.external_id == "bad-offer":
            raise RuntimeError("simulated source persistence failure")

    event.listen(JobSource, "before_insert", fail_first_source)
    try:
        summary = run_ingestion_pipeline(FakeJobConnector(offers), db_session)
    finally:
        event.remove(JobSource, "before_insert", fail_first_source)

    assert (summary.fetched, summary.created, summary.already_known, summary.failed) == (2, 1, 0, 1)
    assert summary.failures[0].provider == "fake"
    assert summary.failures[0].external_id == "bad-offer"
    assert "simulated source persistence failure" in summary.failures[0].message
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1
    assert db_session.scalar(select(Company.name)) == "Company that persists"
