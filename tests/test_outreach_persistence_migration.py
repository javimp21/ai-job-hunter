from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_revision_0006_adds_outreach_schema_and_active_duplicate_constraints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).parents[1]
    database_path = tmp_path / "outreach-migration.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = Config(str(repo_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(alembic_config, "0005_opportunity_workflow")

    company_id = uuid4()
    job_id = uuid4()
    seed_engine = create_engine(database_url)
    with seed_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO companies (id, name) VALUES (:id, :name)"),
            {"id": str(company_id), "name": "Migration Co"},
        )
        connection.execute(
            text("INSERT INTO jobs (id, company_id, title) VALUES (:id, :company_id, :title)"),
            {"id": str(job_id), "company_id": str(company_id), "title": "Backend Engineer"},
        )
    seed_engine.dispose()

    command.upgrade(alembic_config, "0006_outreach_persistence")  # before user_id became required

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"contacts", "outreaches", "outreach_events"} <= set(inspector.get_table_names())
        outreach_columns = {item["name"] for item in inspector.get_columns("outreaches")}
        assert {
            "company_id",
            "job_id",
            "contact_id",
            "application_id",
            "recipient_contact_type",
            "subject",
            "body",
            "status",
        } <= outreach_columns
        index_names = {item["name"] for item in inspector.get_indexes("outreaches")}
        assert {
            "uq_outreach_active_job_contact_purpose",
            "uq_outreach_active_job_without_contact_purpose",
            "uq_outreach_active_company_contact_purpose",
            "uq_outreach_active_company_without_contact_purpose",
        } <= index_names

        contact_id = uuid4()
        outreach_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO contacts (id, company_id, name, contact_type) "
                    "VALUES (:id, :company_id, :name, :contact_type)"
                ),
                {
                    "id": str(contact_id),
                    "company_id": str(company_id),
                    "name": "Fictional Contact",
                    "contact_type": "RECRUITER",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO outreaches "
                    "(id, company_id, job_id, contact_id, purpose, channel, status) "
                    "VALUES (:id, :company_id, :job_id, :contact_id, 'REFERRAL', 'EMAIL', 'DRAFT')"
                ),
                {
                    "id": str(outreach_id),
                    "company_id": str(company_id),
                    "job_id": str(job_id),
                    "contact_id": str(contact_id),
                },
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO outreaches "
                        "(id, company_id, job_id, contact_id, purpose, channel, status) "
                        "VALUES (:id, :company_id, :job_id, :contact_id, 'REFERRAL', 'LINKEDIN', 'DRAFT')"
                    ),
                    {
                        "id": str(uuid4()),
                        "company_id": str(company_id),
                        "job_id": str(job_id),
                        "contact_id": str(contact_id),
                    },
                )
    finally:
        engine.dispose()
