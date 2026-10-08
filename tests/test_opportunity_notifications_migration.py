from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_revision_0008_adds_unique_notification_ledger(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).parents[1]
    database_path = tmp_path / "notifications.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    alembic_config = Config(str(repo_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(repo_root / "alembic"))

    command.upgrade(alembic_config, "0008_opportunity_notifications")  # before user_id became required

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "opportunity_notifications" in inspector.get_table_names()
        columns = {item["name"] for item in inspector.get_columns("opportunity_notifications")}
        assert {
            "job_id",
            "evaluation_fingerprint",
            "channel",
            "status",
            "message",
            "dispatch_started",
            "dispatch_started_at",
            "retryable",
            "provider_message_id",
        } <= columns

        company_id = uuid4()
        job_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO companies (id, name) VALUES (:id, :name)"),
                {"id": str(company_id), "name": "Fictional Company"},
            )
            connection.execute(
                text("INSERT INTO jobs (id, company_id, title) VALUES (:id, :company_id, :title)"),
                {"id": str(job_id), "company_id": str(company_id), "title": "Backend Engineer"},
            )
            connection.execute(
                text(
                    "INSERT INTO opportunity_notifications "
                    "(id, job_id, evaluation_fingerprint, channel, decision, status, message) "
                    "VALUES (:id, :job_id, :fingerprint, 'TELEGRAM', 'APPLY', 'PENDING', 'safe')"
                ),
                {"id": str(uuid4()), "job_id": str(job_id), "fingerprint": "eval-1"},
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO opportunity_notifications "
                        "(id, job_id, evaluation_fingerprint, channel, decision, status, message) "
                        "VALUES (:id, :job_id, :fingerprint, 'TELEGRAM', 'APPLY', 'PENDING', 'safe')"
                    ),
                    {"id": str(uuid4()), "job_id": str(job_id), "fingerprint": "eval-1"},
                )
    finally:
        engine.dispose()
