from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.cli import main
from ai_job_hunter.config import Settings
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.db.base import Base
from ai_job_hunter.models import (
    Company,
    EvaluationStatus,
    HumanReviewStatus,
    Job,
    JobEvaluation,
    OpportunityNotification,
)
from ai_job_hunter.services import notifications
from ai_job_hunter.services.notifications import NotificationPreview, TelegramSendResult
from ai_job_hunter.services.opportunities import Opportunity, RefreshSummary


class FakeTelegramProvider:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, message: str, **kwargs) -> TelegramSendResult:
        self.messages.append(message)
        return TelegramSendResult(message_id="fake-message-id")


def test_run_twice_reuses_refresh_and_does_not_duplicate_notification(
    tmp_path, monkeypatch, capsys
) -> None:
    database_path = tmp_path / "run-notifications.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        company = Company(name="Fictional Company", website_url="https://example.test")
        session.add(company)
        session.flush()
        job = Job(company_id=company.id, title="Backend Engineer", location="Remote — Spain")
        session.add(job)
        session.flush()
        job_id = job.id
        session.add(
            JobEvaluation(
                job_id=job.id,
                evaluation_fingerprint="offer-snapshot-1",
                status=EvaluationStatus.EVALUATED.value,
                decision="APPLY",
                rubric_version="test-rubric",
                policy_version="test-policy",
                engine_name="fake-engine",
                engine_configuration="offline",
                model_version="fake-model",
                config_fingerprint="candidate-config",
                deterministic_result={},
                jev_signals={"role_relevance": {"value": 0.9}},
                evaluated_at=datetime.now(UTC),
            )
        )
        session.commit()

    candidate = CandidateConfig(profile=CandidateProfile())
    opportunity = Opportunity(
        job_id=job_id,
        title="Backend Engineer",
        company="Fictional Company",
        location="Remote — Spain",
        remote_policy="REMOTE",
        employment_type="FULL_TIME",
        url="https://jobs.example.test/role/1",
        technologies=("Python", "PostgreSQL"),
        required_technologies=("Python",),
        salary_min="60000",
        salary_max="80000",
        currency="EUR",
        salary_period="YEAR",
        published_at=None,
        decision=FinalDecision.APPLY,
        evaluation_status=EvaluationStatus.EVALUATED,
        evaluation_is_stale=False,
        review_state=HumanReviewStatus.NEW,
        application_status=None,
        priority=81,
        deterministic_result={},
        jev_signals={},
        jev_reasons={"reasons": []},
        evaluation_fingerprint="offer-snapshot-1",
    )
    monkeypatch.setattr(
        notifications,
        "list_opportunities",
        lambda _session, _candidate, **_kwargs: [opportunity],
    )
    monkeypatch.setattr("ai_job_hunter.cli.load_candidate_config", lambda _path: candidate)
    monkeypatch.setattr("ai_job_hunter.cli.create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        "ai_job_hunter.cli.get_settings",
        lambda: Settings(
            _env_file=None,
            database_url=database_url,
            telegram_bot_token="fake-test-token",
            telegram_chat_id="fake-test-chat",
        ),
    )

    refresh_calls: list[dict[str, object]] = []

    def fake_refresh(_session, _candidate, **kwargs):
        refresh_calls.append(kwargs)
        # Existing Jev cache/evaluation data means this run spends no new calls.
        assert kwargs["max_jev_jobs"] == 0
        return RefreshSummary(jev_cache_hits=1)

    monkeypatch.setattr("ai_job_hunter.cli.refresh_opportunities", fake_refresh)
    provider = FakeTelegramProvider()
    monkeypatch.setattr(
        "ai_job_hunter.cli._configured_telegram_provider", lambda _settings: provider
    )

    command = [
        "run",
        "--limit-companies",
        "1",
        "--max-jobs-per-company",
        "10",
        "--max-jev-jobs",
        "0",
        "--max-notifications",
        "10",
    ]
    assert main(command) == 0
    capsys.readouterr()
    assert main(command) == 0
    output = capsys.readouterr().out

    assert len(refresh_calls) == 2
    assert len(provider.messages) == 1
    assert "sent=0" in output
    assert "reused=1" in output
    assert "Jev cache hits: 1" in output
    with engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(OpportunityNotification))
    assert count == 1
    engine.dispose()


def test_notify_send_dry_run_never_builds_provider_or_writes_ledger(
    tmp_path, monkeypatch, capsys
) -> None:
    database_path = tmp_path / "notify-preview.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    candidate = CandidateConfig(profile=CandidateProfile())

    monkeypatch.setattr("ai_job_hunter.cli.load_candidate_config", lambda _path: candidate)
    monkeypatch.setattr("ai_job_hunter.cli.create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        "ai_job_hunter.cli.get_settings",
        lambda: Settings(
            _env_file=None,
            database_url=database_url,
            telegram_bot_token="fake-test-token",
            telegram_chat_id="fake-test-chat",
        ),
    )
    monkeypatch.setattr(
        "ai_job_hunter.cli._configured_telegram_provider",
        lambda _settings: (_ for _ in ()).throw(AssertionError("dry-run built provider")),
    )
    monkeypatch.setattr(
        "ai_job_hunter.cli.send_notifications",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dry-run attempted delivery")),
    )
    preview = NotificationPreview(
        job_id=uuid4(),
        evaluation_fingerprint="safe-evaluation-hash",
        decision="REVIEW",
        company="Fictional Company",
        title="Backend Engineer",
        location="Remote — Spain",
        priority=81,
        message="👀 REVIEW · Fictional Company — Backend Engineer",
    )
    monkeypatch.setattr(
        "ai_job_hunter.cli.preview_notifications", lambda *_args, **_kwargs: [preview]
    )

    assert main(["notify", "send", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "NOTIFICATION DRY RUN: 1 eligible alert" in output
    assert "Fictional Company — Backend Engineer" in output
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(OpportunityNotification)) == 0
    engine.dispose()
