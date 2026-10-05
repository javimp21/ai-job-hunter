import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import (
    Company,
    HumanReviewStatus,
    Job,
    JobReview,
    JobSource,
    MonitoredSource,
    OpportunityNotification,
    ReportDelivery,
)
from ai_job_hunter.services import weekly_report as weekly
from ai_job_hunter.services.weekly_report import (
    WEEKLY_KIND,
    build_weekly_report,
    format_weekly_message,
    preview_weekly,
    send_weekly,
)
from tests.test_notifications import FakeProvider, RejectedProvider, _opportunity

NOW = datetime(2026, 10, 4, 19, 0, tzinfo=UTC)
PASS = {"decision": "PASS"}
REJECT = {"decision": "REJECT"}


def _candidate():
    return CandidateConfig(
        profile=CandidateProfile(technologies=["Java", "Spring"], primary_skills=["Kotlin"])
    )


def _seed_job(session, *, age_days, provider="greenhouse", company="Example Co"):
    row = session.scalar(select(Company).where(Company.name == company))
    if row is None:
        row = Company(name=company, website_url="https://example.test")
        session.add(row)
        session.flush()
    job = Job(company_id=row.id, title="Backend Engineer", created_at=NOW - timedelta(days=age_days))
    session.add(job)
    session.flush()
    session.add(JobSource(job_id=job.id, provider=provider, external_id=str(job.id)))
    session.commit()
    return job


def _item(job, decision, **changes):
    base = _opportunity(job.id, decision, 80 if decision else None, company=job.company.name)
    values = {
        "first_seen_at": job.created_at,
        "deterministic_result": PASS,
        "technologies": ("Java", "Kubernetes"),
        "required_technologies": ("Java",),
        "salary_min": "50000",
        "salary_max": "70000",
        "currency": "EUR",
        "salary_period": "YEAR",
    }
    values.update(changes)
    return dataclasses.replace(base, **values)


def _install(monkeypatch, items):
    monkeypatch.setattr(weekly, "list_opportunities", lambda session, candidate, **kwargs: items)


def _ledger(session, job, channel, *, sent_at, status="SENT", fingerprint="fp"):
    session.add(
        OpportunityNotification(
            job_id=job.id,
            evaluation_fingerprint=f"{fingerprint}-{channel}-{sent_at.isoformat()}",
            channel=channel,
            decision="APPLY",
            status=status,
            message="m",
            sent_at=sent_at,
        )
    )
    session.commit()


def _review(session, job, state, reason, *, updated_at):
    session.add(JobReview(job_id=job.id, state=state.value, reason=reason, updated_at=updated_at))
    session.commit()


def _seeded(db_session, monkeypatch):
    jobs = [_seed_job(db_session, age_days=1, provider="greenhouse") for _ in range(4)]
    jobs.append(_seed_job(db_session, age_days=2, provider="lever", company="Other Co"))
    old = _seed_job(db_session, age_days=20)  # outside the window
    rejected = _seed_job(db_session, age_days=1)  # prefilter REJECT
    pending = _seed_job(db_session, age_days=1)  # passed prefilter, not evaluated yet
    items = [
        _item(jobs[0], FinalDecision.APPLY),
        _item(jobs[1], FinalDecision.REVIEW),
        _item(jobs[2], FinalDecision.REVIEW, salary_min="3000", salary_max=None, salary_period="MONTH"),
        _item(jobs[3], FinalDecision.REVIEW, currency="USD"),
        _item(jobs[4], FinalDecision.SKIP),
        _item(old, FinalDecision.APPLY),
        _item(rejected, FinalDecision.SKIP, deterministic_result=REJECT),
        _item(pending, None),
    ]
    _install(monkeypatch, items)
    return jobs, old


def test_funnel_counts_only_the_window(db_session, monkeypatch):
    jobs, old = _seeded(db_session, monkeypatch)

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert report.discovered == 7  # 8 jobs minus the one created 20 days ago
    assert report.passed_prefilter == 6  # all in-window but the REJECT
    assert report.evaluated == 5  # the pending one has no decision
    assert (report.apply, report.review) == (1, 3)


def test_alerts_and_digest_items_sent_in_window(db_session, monkeypatch):
    jobs, old = _seeded(db_session, monkeypatch)
    _ledger(db_session, jobs[0], "TELEGRAM", sent_at=NOW - timedelta(days=1))
    _ledger(db_session, jobs[1], "TELEGRAM", sent_at=NOW - timedelta(days=9))  # too old
    _ledger(db_session, jobs[2], "TELEGRAM", sent_at=NOW - timedelta(days=1), status="FAILED")
    _ledger(db_session, jobs[3], "TELEGRAM_DIGEST", sent_at=NOW - timedelta(days=2))
    _ledger(db_session, jobs[4], "TELEGRAM_DIGEST", sent_at=NOW - timedelta(days=2))

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert (report.alerts_sent, report.digest_items) == (1, 2)


def test_top_companies_sources_and_technologies(db_session, monkeypatch):
    _seeded(db_session, monkeypatch)

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert report.top_companies == (("Example Co", 4),)  # SKIP and old jobs are not relevant
    assert report.top_sources == (("greenhouse", 4),)
    java, kubernetes = report.technologies
    assert (java.name, java.jobs, java.in_stack) == ("Java", 4, True)
    assert (kubernetes.name, kubernetes.jobs, kubernetes.in_stack) == ("Kubernetes", 4, False)


def test_salary_is_eur_yearly_without_conversion(db_session, monkeypatch):
    _seeded(db_session, monkeypatch)

    salary = build_weekly_report(db_session, _candidate(), now=NOW).salary

    # 60k midpoint (x2 jobs), 36k from 3000/month; the USD job is ignored.
    assert salary.count == 3
    assert salary.relevant == 4
    assert salary.median == Decimal(60000)
    assert (salary.minimum, salary.maximum) == (Decimal(36000), Decimal(70000))


def test_no_eur_salary_is_reported_as_missing(db_session, monkeypatch):
    job = _seed_job(db_session, age_days=1)
    _install(monkeypatch, [_item(job, FinalDecision.APPLY, salary_min=None, salary_max=None)])

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert report.salary is None
    assert "Ninguna oferta relevante publica salario" in format_weekly_message(report)


def test_feedback_counts_reasons_and_saved_vs_dismissed_technologies(db_session, monkeypatch):
    jobs, old = _seeded(db_session, monkeypatch)
    recent = NOW - timedelta(days=1)
    _review(db_session, jobs[0], HumanReviewStatus.SAVED, "stack", updated_at=recent)
    _review(db_session, jobs[1], HumanReviewStatus.DISMISSED, "salary", updated_at=recent)
    _review(db_session, jobs[2], HumanReviewStatus.DISMISSED, "salary", updated_at=recent)
    _review(db_session, jobs[3], HumanReviewStatus.DISMISSED, None, updated_at=recent)
    _review(db_session, old, HumanReviewStatus.DISMISSED, "role", updated_at=NOW - timedelta(days=30))
    _review(db_session, jobs[4], HumanReviewStatus.SEEN, None, updated_at=recent)

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert (report.thumbs_up, report.thumbs_down) == (1, 3)
    assert report.reasons_up == (("stack", 1),)
    assert dict(report.reasons_down) == {"salario": 2, "sin motivo": 1}
    assert [t.name for t in report.technologies_saved] == ["Java", "Kubernetes"]
    assert report.technologies_dismissed[0].jobs == 3


def test_failing_sources_are_listed(db_session, monkeypatch):
    job = _seed_job(db_session, age_days=1)
    _install(monkeypatch, [])
    db_session.add(
        MonitoredSource(
            company_id=job.company_id,
            provider="lever",
            identifier="example",
            identifier_key="example",
            state="ACTIVE",
            origin="career_url",
            consecutive_failures=9,
        )
    )
    db_session.commit()

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert report.failing_sources == ("Example Co (Lever, 9 fallos)",)
    assert any("fuente(s)" in text for text in report.suggestions)


def test_suggestions_come_only_from_the_numbers(db_session, monkeypatch):
    jobs, _old = _seeded(db_session, monkeypatch)
    recent = NOW - timedelta(days=1)
    for job in jobs[:3]:
        _review(db_session, job, HumanReviewStatus.DISMISSED, "salary", updated_at=recent)

    report = build_weekly_report(db_session, _candidate(), now=NOW)

    assert len(report.suggestions) <= 3
    assert any("4 de 4 ofertas relevantes piden Kubernetes" in text for text in report.suggestions)
    assert any("3 de tus 3 👎 son por «salario»" in text for text in report.suggestions)


def test_empty_week_has_no_invented_numbers_or_suggestions(db_session, monkeypatch):
    _install(monkeypatch, [])

    report = build_weekly_report(db_session, _candidate(), now=NOW)
    message = format_weekly_message(report)

    assert report.discovered == 0 and report.salary is None
    assert "0 descubiertas → 0 pasan el filtro → 0 evaluadas" in message
    assert "revisa que las fuentes" in message


def test_message_is_html_escaped_and_short(db_session, monkeypatch):
    job = _seed_job(db_session, age_days=1, company="Evil <b>&Co")
    _install(monkeypatch, [_item(job, FinalDecision.APPLY, technologies=("C<script>",), required_technologies=())])

    message = format_weekly_message(build_weekly_report(db_session, _candidate(), now=NOW))

    assert "<script>" not in message and "Evil <b>" not in message
    assert "Evil &lt;b&gt;&amp;Co" in message
    assert len(message) < 4096


def test_send_records_marker_and_waits_six_days(db_session, monkeypatch):
    _seeded(db_session, monkeypatch)
    provider = FakeProvider()

    first = send_weekly(db_session, _candidate(), provider, now=NOW)
    again = send_weekly(db_session, _candidate(), provider, now=NOW + timedelta(days=5))
    next_week = send_weekly(db_session, _candidate(), provider, now=NOW + timedelta(days=7))

    assert (first.status, again.status, next_week.status) == ("sent", "too_soon", "sent")
    assert len(provider.messages) == 2
    rows = db_session.scalars(select(ReportDelivery)).all()
    assert [row.kind for row in rows] == [WEEKLY_KIND, WEEKLY_KIND]
    assert rows[0].provider_message_id == "msg-123"


def test_force_overrides_marker_and_failure_records_nothing(db_session, monkeypatch):
    _seeded(db_session, monkeypatch)
    provider = FakeProvider()
    send_weekly(db_session, _candidate(), provider, now=NOW)

    forced = send_weekly(db_session, _candidate(), provider, now=NOW + timedelta(hours=1), force=True)
    failed = send_weekly(db_session, _candidate(), RejectedProvider(), now=NOW + timedelta(days=30))

    assert (forced.status, failed.status) == ("sent", "failed")
    assert len(db_session.scalars(select(ReportDelivery)).all()) == 2


def test_preview_writes_nothing(db_session, monkeypatch):
    _seeded(db_session, monkeypatch)

    result = preview_weekly(db_session, _candidate(), now=NOW)

    assert result.status == "preview" and "Resumen semanal" in result.message
    assert db_session.scalars(select(ReportDelivery)).all() == []


def test_migration_0013_creates_marker_table(tmp_path, monkeypatch):
    from pathlib import Path

    repo_root = Path(__file__).parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'weekly.sqlite3').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("report_deliveries")}
        assert {"kind", "period_start", "period_end", "provider_message_id", "sent_at"} <= columns
    finally:
        engine.dispose()
    command.downgrade(config, "0012_notification_digest_channel")
    engine = create_engine(database_url)
    try:
        assert "report_deliveries" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
