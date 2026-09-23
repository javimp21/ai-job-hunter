from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, configure_mappers

from ai_job_hunter.db.base import Base
from ai_job_hunter.models import Company, Job, JobSource


def test_models_import_and_relationships_are_configured() -> None:
    configure_mappers()

    assert set(Base.metadata.tables) == {"companies", "jobs", "job_sources"}
    assert Company.jobs.property.mapper.class_ is Job
    assert Job.company.property.mapper.class_ is Company
    assert Job.sources.property.mapper.class_ is JobSource
    assert JobSource.job.property.mapper.class_ is Job


def test_company_job_and_multiple_source_relationships() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        company = Company(name="Example employer")
        session.add(company)
        session.commit()
        assert company.jobs == []

        job = Job(title="Software Engineer", company=company)
        job.sources.extend(
            [
                JobSource(provider="careers", original_url="https://example.test/jobs/1"),
                JobSource(
                    provider="linkedin",
                    external_id="job-1",
                    original_url="https://linkedin.example/jobs/job-1",
                    raw_metadata={"department": "Engineering"},
                ),
            ]
        )
        session.add(job)
        session.commit()

        loaded_job = session.scalars(select(Job)).one()
        assert loaded_job.company is not None
        assert loaded_job.company.name == "Example employer"
        assert loaded_job.id is not None
        assert loaded_job.created_at is not None
        assert loaded_job.updated_at is not None
        assert len(loaded_job.sources) == 2
        source_with_metadata = next(
            source for source in loaded_job.sources if source.raw_metadata is not None
        )
        assert source_with_metadata.raw_metadata == {"department": "Engineering"}
        assert source_with_metadata.discovered_at is not None
        assert inspect(loaded_job).persistent

    engine.dispose()
