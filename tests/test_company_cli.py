from __future__ import annotations

from sqlalchemy import create_engine, func, select

from ai_job_hunter import company_cli
from ai_job_hunter.db.base import Base
from ai_job_hunter.db.session import create_session_factory
from ai_job_hunter.models import Company, CompanyEvidence, Job, JobSource
from ai_job_hunter.services.company_intelligence import (
    CompanyMonitorFilters,
    build_company_monitor_targets,
)


def test_show_unknown_company_keeps_absent_facts_unknown(monkeypatch, capsys) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(company_cli, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(company_cli, "create_session_factory", create_session_factory)

    try:
        assert company_cli.main(["show", "Unlisted Example"]) == 0
    finally:
        engine.dispose()

    output = capsys.readouterr().out
    assert "Evidence: none in the imported sources" in output
    assert "Remote from Spain: UNKNOWN" in output
    assert "Public salary: UNKNOWN" in output
    assert "Company type: UNKNOWN" in output


def test_monitor_commits_observed_ats_evidence_for_later_refresh(
    monkeypatch, tmp_path, capsys
) -> None:
    database_path = tmp_path / "company-cli.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory
    monkeypatch.setattr(company_cli, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(company_cli, "create_session_factory", session_factory)

    class EmptyConnector:
        def fetch_jobs(self):
            return []

    monkeypatch.setattr(
        company_cli,
        "build_job_connectors",
        lambda config, **_kwargs: [EmptyConnector() for _ in config.sources],
    )
    with session_factory(engine)() as session:
        company = Company(name="Example Company", website_url="https://example.test")
        job = Job(company=company, title="Backend Engineer", description="Backend role")
        session.add(
            JobSource(
                job=job,
                provider="greenhouse",
                external_id="example-role-1",
                original_url="https://boards.greenhouse.io/example-company/jobs/123",
                canonical_url="https://boards.greenhouse.io/example-company/jobs/123",
            )
        )
        session.commit()

    snapshot_path = tmp_path / "monitor-jobs.local.json"
    assert company_cli.main(
        [
            "monitor",
            "--supported-ats",
            "--limit-companies",
            "1",
            "--max-jobs-per-company",
            "1",
            "--save-snapshot",
            str(snapshot_path),
            "--database-url",
            database_url,
        ]
    ) == 0
    capsys.readouterr()

    verify_engine = create_engine(database_url)
    with session_factory(verify_engine)() as session:
        assert session.scalar(select(func.count()).select_from(CompanyEvidence)) == 1
        targets = build_company_monitor_targets(
            session,
            CompanyMonitorFilters(supported_ats=True),
            limit_companies=1,
        )
        assert len(targets) == 1
        assert targets[0].provider.value == "GREENHOUSE"

    verify_engine.dispose()
