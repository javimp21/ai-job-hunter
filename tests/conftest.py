from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_job_hunter.db.base import Base
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    NormalizedJob,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def fake_offer_batch() -> tuple[NormalizedJob, NormalizedJob, NormalizedJob]:
    discovered_at = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    original = NormalizedJob(
        provider="example-board",
        external_id="acme-platform-1",
        source_url="https://jobs.example.test/acme/platform-1",
        title="Platform Engineer",
        company_name="Acme Robotics",
        company_website="https://acme.example.test",
        description="Build platform services.",
        location="Barcelona, Spain",
        remote_policy=RemotePolicy.HYBRID,
        remote_eligibility=RemoteEligibility.SPAIN_ONLY,
        salary_min="60000.00",
        salary_max="75000.00",
        currency="eur",
        salary_period=SalaryPeriod.YEAR,
        employment_type=EmploymentType.FULL_TIME,
        published_at=datetime(2026, 9, 18, 8, 0, tzinfo=UTC),
        discovered_at=discovered_at,
        raw_metadata={"team": "Platform"},
    )
    same_company = NormalizedJob(
        provider="example-board",
        external_id="acme-data-2",
        source_url="https://jobs.example.test/acme/data-2",
        title="Data Engineer",
        company_name="ACME ROBOTICS",
        location="Madrid, Spain",
        discovered_at=discovered_at,
    )
    refreshed_payload = original.model_dump()
    refreshed_payload.update(
        {
            "title": "Senior Platform Engineer",
            "description": "Build and operate platform services.",
            "salary_min": 70000,
            "salary_max": 85000,
            "discovered_at": datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
            "raw_metadata": {"team": "Platform", "level": "Senior"},
        }
    )
    refreshed = NormalizedJob.model_validate(refreshed_payload)
    return original, same_company, refreshed
