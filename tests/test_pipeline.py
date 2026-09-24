from sqlalchemy import event, func, select

from ai_job_hunter.connectors import FakeJobConnector
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource
from ai_job_hunter.services.pipeline import run_ingestion_pipeline


def test_pipeline_summary_ingests_fake_batch_and_reuses_company(
    db_session, fake_offer_batch
) -> None:
    summary = run_ingestion_pipeline(FakeJobConnector(fake_offer_batch), db_session)

    assert (
        summary.fetched,
        summary.created,
        summary.already_known,
        summary.matched_existing,
        summary.possible_match,
        summary.failed,
    ) == (3, 2, 1, 0, 0, 0)
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

    assert (
        summary.fetched,
        summary.created,
        summary.already_known,
        summary.matched_existing,
        summary.possible_match,
        summary.failed,
    ) == (2, 1, 0, 0, 0, 1)
    assert summary.failures[0].provider == "fake"
    assert summary.failures[0].external_id == "bad-offer"
    assert "simulated source persistence failure" in summary.failures[0].message
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1
    assert db_session.scalar(select(Company.name)) == "Company that persists"


def test_pipeline_reports_matched_and_possible_offers(db_session) -> None:
    first = NormalizedJob(
        provider="first-board",
        external_id="role-1",
        title="Backend Engineer",
        company_name="Acme",
        company_website="https://acme.example.test",
        canonical_url="https://jobs.acme.example/jobs/backend-1",
    )
    exact_repeat = first.model_copy()
    matched = NormalizedJob(
        provider="second-board",
        external_id="role-2",
        title="Backend Software Engineer",
        company_name="Acme Inc.",
        company_website="https://acme.example.test",
        canonical_url="https://jobs.acme.example/jobs/backend-1",
    )
    possible = NormalizedJob(
        provider="third-board",
        external_id="role-3",
        title="Backend Engineer",
        company_name="Acme",
        company_website="https://acme.example.test",
    )

    summary = run_ingestion_pipeline(
        FakeJobConnector((first, exact_repeat, matched, possible)),
        db_session,
    )

    assert (
        summary.fetched,
        summary.created,
        summary.already_known,
        summary.matched_existing,
        summary.possible_match,
        summary.failed,
    ) == (4, 1, 1, 1, 1, 0)
    assert len(summary.matched_results) == 1
    assert len(summary.possible_matches) == 1
    assert summary.possible_matches[0].possible_matches[0].reasons
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 3


def test_greenhouse_and_lever_use_existing_idempotency_and_cross_source_matching(db_session) -> None:
    greenhouse = NormalizedJob(
        provider="greenhouse",
        external_id="gh-501",
        source_url="https://boards.greenhouse.io/exampleco/jobs/501",
        canonical_url="https://boards.greenhouse.io/exampleco/jobs/501",
        title="Backend Engineer",
        company_name="Example Co",
        location="Barcelona, Spain",
        description="Build backend APIs.",
    )
    lever = NormalizedJob(
        provider="lever",
        external_id="lv-900",
        source_url="https://jobs.lever.co/exampleco/lv-900",
        canonical_url="https://boards.greenhouse.io/exampleco/jobs/501",
        title="Backend Engineer",
        company_name="Example Co",
        location="Barcelona, Spain",
    )

    first = run_ingestion_pipeline(FakeJobConnector((greenhouse, lever)), db_session)
    second = run_ingestion_pipeline(FakeJobConnector((greenhouse, lever)), db_session)

    assert (first.fetched, first.created, first.matched_existing, first.failed) == (2, 1, 1, 0)
    assert (second.fetched, second.already_known, second.failed) == (2, 2, 0)
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 2
