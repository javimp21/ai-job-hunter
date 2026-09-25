from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_revision_0005_preserves_rows_backfills_sources_and_creates_workflow_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = Path(__file__).parents[1]
    database_path = tmp_path / "workflow-migration.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = Config(str(repo_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(alembic_config, "0004_company_evidence")

    company_id = uuid4()
    job_id = uuid4()
    source_id = uuid4()
    seed_engine = create_engine(database_url)
    with seed_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO companies (id, name, website_url) "
                "VALUES (:id, :name, :website_url)"
            ),
            {
                "id": str(company_id),
                "name": "Migration Fixture Co",
                "website_url": "https://migration-fixture.example.test",
            },
        )
        connection.execute(
            text(
                "INSERT INTO jobs (id, company_id, title, description, location, remote_policy) "
                "VALUES (:id, :company_id, :title, :description, :location, :remote_policy)"
            ),
            {
                "id": str(job_id),
                "company_id": str(company_id),
                "title": "Platform Engineer",
                "description": "Own platform services and deployments.",
                "location": "Madrid, Spain",
                "remote_policy": "HYBRID",
            },
        )
        connection.execute(
            text(
                "INSERT INTO job_sources "
                "(id, job_id, provider, external_id, original_url, canonical_url, company_website) "
                "VALUES (:id, :job_id, :provider, :external_id, :original_url, :canonical_url, :company_website)"
            ),
            {
                "id": str(source_id),
                "job_id": str(job_id),
                "provider": "greenhouse",
                "external_id": "migration-role-1",
                "original_url": "https://boards.greenhouse.io/migrationfixture/jobs/1",
                "canonical_url": "https://boards.greenhouse.io/migrationfixture/jobs/1",
                "company_website": "https://migration-fixture.example.test",
            },
        )
    seed_engine.dispose()

    # Alembic reads DATABASE_URL from the test environment, so this upgrades
    # only the isolated file created under pytest's temporary directory.
    command.upgrade(alembic_config, "head")

    final_engine = create_engine(database_url)
    try:
        inspector = inspect(final_engine)
        assert {
            "applications",
            "application_events",
            "job_evaluations",
            "job_reviews",
        } <= set(inspector.get_table_names())

        application_columns = {column["name"] for column in inspector.get_columns("applications")}
        assert {
            "applied_at",
            "source",
            "notes",
            "application_url",
            "cv_version",
        } <= application_columns

        with final_engine.connect() as connection:
            company = connection.execute(
                text("SELECT name, website_url FROM companies WHERE id = :id"),
                {"id": str(company_id)},
            ).one()
            job = connection.execute(
                text("SELECT title, description, location FROM jobs WHERE id = :id"),
                {"id": str(job_id)},
            ).one()
            source = connection.execute(
                text(
                    "SELECT provider, external_id, source_title, source_description, source_location "
                    "FROM job_sources WHERE id = :id"
                ),
                {"id": str(source_id)},
            ).one()

        assert company == ("Migration Fixture Co", "https://migration-fixture.example.test")
        assert job == (
            "Platform Engineer",
            "Own platform services and deployments.",
            "Madrid, Spain",
        )
        assert source == (
            "greenhouse",
            "migration-role-1",
            "Platform Engineer",
            "Own platform services and deployments.",
            "Madrid, Spain",
        )
    finally:
        final_engine.dispose()
