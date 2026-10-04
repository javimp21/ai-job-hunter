from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.domain.company_intelligence import CompanyEvidenceType
from ai_job_hunter.models import Company, CompanyEvidence, MonitoredSource, MonitoredSourceState
from ai_job_hunter.services import opportunities
from ai_job_hunter.services.company_intelligence import CompanyMonitorFilters
from ai_job_hunter.services.monitored_sources import (
    preview_source,
    MonitoredSourceError,
    active_monitor_targets,
    list_sources,
    record_fetch_results,
    set_source_state,
    sync_monitored_sources,
)
from ai_job_hunter.services.opportunities import SourceFailure


def _company(session, name: str, board: str, *, provider: str = "GREENHOUSE") -> Company:
    company = Company(name=name, website_url=f"https://{board}.example.test")
    company.evidence_items.append(
        CompanyEvidence(
            provider="observed_job_source",
            source_key=f"{board}:{provider.casefold()}",
            source_url=f"https://boards.greenhouse.io/{board}",
            external_identifier=board,
            evidence_type=CompanyEvidenceType.ATS_OBSERVED.value,
            structured_data={
                "ats_provider": provider,
                "identifier": board,
                "region": None,
                "supporting_job_sources": [{"source_url": f"https://boards.greenhouse.io/{board}/jobs/1"}],
            },
        )
    )
    session.add(company)
    session.commit()
    return company


def _source(session, board: str) -> MonitoredSource:
    return session.scalar(select(MonitoredSource).where(MonitoredSource.identifier_key == board))


def test_revision_0009_creates_unique_board_table(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'sources.sqlite3').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        assert "monitored_sources" in inspect(engine).get_table_names()
        company_id = str(uuid4())
        insert = text(
            "INSERT INTO monitored_sources (id, company_id, provider, identifier, identifier_key, origin) "
            "VALUES (:id, :company, 'GREENHOUSE', 'Acme', 'acme', 'career_url')"
        )
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO companies (id, name) VALUES (:id, 'Acme')"), {"id": company_id})
            connection.execute(insert, {"id": str(uuid4()), "company": company_id})
            state = connection.execute(text("SELECT state FROM monitored_sources")).scalar()
        assert state == "REVIEW_SOURCE"
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(insert, {"id": str(uuid4()), "company": company_id})
        command.downgrade(config, "0008_opportunity_notifications")
        assert "monitored_sources" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_sync_records_new_boards_for_review_only_once(db_session) -> None:
    _company(db_session, "Acme", "acme")

    first = sync_monitored_sources(db_session)
    second = sync_monitored_sources(db_session, activate_new=True)

    assert (first.created, first.activated) == (1, 0)
    assert (second.created, second.activated, second.existing) == (0, 0, 1)
    row = _source(db_session, "acme")
    assert row.state == MonitoredSourceState.REVIEW_SOURCE.value
    assert row.origin == "observed_job_source"
    assert row.careers_url == "https://boards.greenhouse.io/acme"


def test_sync_can_adopt_existing_boards_and_reports_conflicts(db_session) -> None:
    _company(db_session, "Acme", "acme")
    adopted = sync_monitored_sources(db_session, activate_new=True, reason="already monitored")
    _company(db_session, "Acme Duplicate", "ACME")

    conflict = sync_monitored_sources(db_session)

    assert adopted.activated == 1
    assert _source(db_session, "acme").state_reason == "already monitored"
    assert conflict.conflicts == 1
    assert db_session.scalar(select(MonitoredSource).where(MonitoredSource.identifier_key == "acme")) is not None
    assert len(list_sources(db_session)) == 1


def test_only_active_boards_are_targets_least_recently_fetched_first(db_session) -> None:
    for name in ("Alpha", "Beta", "Gamma"):
        _company(db_session, name, name.casefold())
    sync_monitored_sources(db_session)
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    alpha, beta, gamma = (_source(db_session, name) for name in ("alpha", "beta", "gamma"))
    for row in (alpha, beta):
        set_source_state(db_session, row.id, MonitoredSourceState.ACTIVE, reason="looks good", now=now)
    alpha.last_fetched_at = now
    beta.last_fetched_at = now - timedelta(hours=4)
    db_session.commit()

    targets = active_monitor_targets(db_session, CompanyMonitorFilters(supported_ats=True), limit_companies=10)
    limited = active_monitor_targets(db_session, limit_companies=1)

    assert [target.company_name for target in targets] == ["Beta", "Alpha"]
    assert targets[0].source_id == beta.id
    assert [target.company_name for target in limited] == ["Beta"]
    assert gamma.state == MonitoredSourceState.REVIEW_SOURCE.value
    with pytest.raises(ValueError):
        active_monitor_targets(db_session, limit_companies=0)


def test_state_changes_and_unknown_ids(db_session) -> None:
    _company(db_session, "Acme", "acme")
    sync_monitored_sources(db_session)
    row = _source(db_session, "acme")
    row.consecutive_failures = 3
    db_session.commit()

    set_source_state(db_session, row.id, MonitoredSourceState.REJECTED, reason="Too many sales roles")
    assert row.state_reason == "Too many sales roles"
    set_source_state(db_session, row.id, MonitoredSourceState.ACTIVE)
    assert row.state == "ACTIVE" and row.consecutive_failures == 0
    with pytest.raises(MonitoredSourceError):
        set_source_state(db_session, uuid4(), MonitoredSourceState.PAUSED)


def test_fetch_results_record_counts_and_failures(db_session) -> None:
    for name in ("Alpha", "Beta"):
        _company(db_session, name, name.casefold())
    sync_monitored_sources(db_session, activate_new=True)
    targets = active_monitor_targets(db_session)
    alpha = next(target for target in targets if target.company_name == "Alpha")
    now = datetime(2026, 10, 3, 14, tzinfo=UTC)

    record_fetch_results(
        db_session,
        targets,
        [(object(), alpha), (object(), alpha)],
        [SourceFailure("Beta", "GREENHOUSE", "GreenhouseConnectorError")],
        now=now,
    )

    alpha_row, beta_row = _source(db_session, "alpha"), _source(db_session, "beta")
    assert (alpha_row.last_fetch_status, alpha_row.last_job_count) == ("OK", 2)
    assert (beta_row.last_fetch_status, beta_row.consecutive_failures) == ("FAILED", 1)
    assert beta_row.last_fetch_error == "GreenhouseConnectorError"
    assert alpha_row.last_fetched_at is not None and beta_row.last_fetched_at is not None


def test_refresh_never_fetches_boards_waiting_for_review(db_session, monkeypatch, tmp_path) -> None:
    _company(db_session, "Reviewed", "reviewed")
    sync_monitored_sources(db_session, activate_new=True)
    _company(db_session, "Newcomer", "newcomer")
    fetched_companies: list[str] = []

    def fake_fetch(targets, *, max_jobs_per_company, client):
        fetched_companies.extend(target.company_name for target in targets)
        return [], []

    monkeypatch.setattr(opportunities, "_fetch_targets", fake_fetch)

    opportunities.refresh_opportunities(
        db_session,
        load_candidate_config(Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"),
        no_jev=True,
        engine=type("Engine", (), {"cache_identity": "offline"})(),
        cache=DecisionCache(tmp_path / "c.json"),
    )

    assert fetched_companies == ["Reviewed"]
    newcomer = _source(db_session, "newcomer")
    assert newcomer.state == MonitoredSourceState.REVIEW_SOURCE.value
    assert _source(db_session, "reviewed").last_fetched_at is not None


def test_lead_derived_active_board_becomes_a_target(db_session) -> None:
    company = Company(name="Duna", website_url="https://duna.example.test")
    db_session.add(company)
    db_session.flush()
    db_session.add(
        MonitoredSource(
            company_id=company.id,
            provider="ASHBY",
            identifier="duna",
            identifier_key="duna",
            careers_url="https://jobs.ashbyhq.com/duna",
            state=MonitoredSourceState.ACTIVE.value,
            origin="career_url",
        )
    )
    db_session.commit()

    (target,) = active_monitor_targets(db_session)

    assert target.provider.value == "ASHBY"
    assert target.evidence_source == "career_url"
    assert target.confidence.value == "DIRECT_URL_PATTERN"


def test_preview_summarizes_board_without_ingesting(db_session, monkeypatch) -> None:
    from ai_job_hunter.connectors import factory
    from ai_job_hunter.domain.normalized_job import NormalizedJob
    from ai_job_hunter.models import Job

    _company(db_session, "Acme", "acme")
    sync_monitored_sources(db_session)
    row = _source(db_session, "acme")

    def offer(title: str, location: str) -> NormalizedJob:
        return NormalizedJob(
            provider="greenhouse", external_id=title, source_url=f"https://example.test/{len(title)}",
            title=title, company_name="Acme", location=location, remote_policy="REMOTE",
            remote_eligibility="SPAIN_ONLY" if "Spain" in location else "COUNTRY_RESTRICTED",
        )

    class FakeConnector:
        def fetch_jobs(self):
            return [offer("Backend Engineer", "Remote Spain"), offer("Account Executive", "Remote Spain"),
                    offer("Backend Engineer II", "Remote US")]

    monkeypatch.setattr(factory, "build_job_connectors", lambda config, client=None: [FakeConnector()])
    stats = preview_source(db_session, row.id, load_candidate_config(Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"))

    assert stats["jobs"] == 3
    assert stats["prefilter_pass_or_review"] == 1
    assert stats["examples"] == ["Backend Engineer — Remote Spain"]
    assert row.preview_stats["jobs"] == 3
    assert row.state == MonitoredSourceState.REVIEW_SOURCE.value
    assert db_session.query(Job).count() == 0


def test_lever_boards_are_polled_at_most_every_two_hours(db_session) -> None:
    _company(db_session, "Leverco", "leverco", provider="LEVER")
    _company(db_session, "Greenco", "greenco")
    sync_monitored_sources(db_session)
    now = datetime(2026, 10, 4, 18, tzinfo=UTC)
    lever, green = _source(db_session, "leverco"), _source(db_session, "greenco")
    for row in (lever, green):
        set_source_state(db_session, row.id, MonitoredSourceState.ACTIVE, reason="ok", now=now)
        row.last_fetched_at = now - timedelta(minutes=30)
    db_session.commit()

    soon = active_monitor_targets(db_session, now=now)
    later = active_monitor_targets(db_session, now=now + timedelta(hours=2))

    assert [target.company_name for target in soon] == ["Greenco"]
    assert {target.company_name for target in later} == {"Greenco", "Leverco"}
