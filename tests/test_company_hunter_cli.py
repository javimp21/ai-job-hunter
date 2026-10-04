import logging
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from company_hunter_support import add_company, add_contact
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_hunter.cli import main


@pytest.fixture(autouse=True)
def keep_logging_state():
    """alembic's env.py reconfigures logging and disables existing loggers; undo it for later tests."""

    manager = logging.root.manager
    disabled = {name: logger.disabled for name, logger in manager.loggerDict.items() if isinstance(logger, logging.Logger)}
    handlers, level = list(logging.root.handlers), logging.root.level
    yield
    for name, logger in manager.loggerDict.items():
        if isinstance(logger, logging.Logger):
            logger.disabled = disabled.get(name, False)
    logging.root.handlers[:] = handlers
    logging.root.setLevel(level)


def migrated_database(tmp_path: Path, monkeypatch, target="head") -> tuple[str, Config]:
    repo_root = Path(__file__).parents[1]
    url = f"sqlite+pysqlite:///{(tmp_path / 'hunter.sqlite3').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(config, target)
    return url, config


def test_migration_0013_adds_connection_requests_and_per_channel_company_outreach(tmp_path, monkeypatch):
    url, config = migrated_database(tmp_path, monkeypatch)
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "connection_requests" in inspector.get_table_names()
        columns = {item["name"] for item in inspector.get_columns("connection_requests")}
        assert {"contact_id", "company_id", "status", "note", "suggested_at", "sent_at", "accepted_at", "skip_until",
                "telegram_message_id", "grounding_post", "follow_up_draft", "language"} <= columns
        indexes = {item["name"]: item for item in inspector.get_indexes("outreaches")}
        assert indexes["uq_outreach_active_company_without_contact_purpose"]["column_names"] == [
            "company_id", "channel", "purpose"
        ]

        company, contact, request = str(uuid4()), str(uuid4()), str(uuid4())
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO companies (id, name) VALUES (:i, 'Co')"), {"i": company})
            connection.execute(
                text("INSERT INTO contacts (id, company_id, name, contact_type) VALUES (:i, :c, 'P', 'ENGINEER')"),
                {"i": contact, "c": company},
            )
            # An email and a LinkedIn draft for the same company coexist; two emails do not.
            for channel in ("EMAIL", "LINKEDIN"):
                connection.execute(
                    text("INSERT INTO outreaches (id, company_id, purpose, channel, status) "
                         "VALUES (:i, :c, 'COLD_OUTREACH', :ch, 'DRAFT')"),
                    {"i": str(uuid4()), "c": company, "ch": channel},
                )
            connection.execute(
                text("INSERT INTO connection_requests (id, contact_id, company_id, language, note, suggested_at) "
                     "VALUES (:i, :ct, :c, 'es', 'hola', '2026-10-05 08:00:00')"),
                {"i": request, "ct": contact, "c": company},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO outreaches (id, company_id, purpose, channel, status) "
                         "VALUES (:i, :c, 'COLD_OUTREACH', 'EMAIL', 'DRAFT')"),
                    {"i": str(uuid4()), "c": company},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO connection_requests (id, contact_id, company_id, language, note, suggested_at) "
                         "VALUES (:i, :ct, :c, 'es', :n, '2026-10-05 08:00:00')"),
                    {"i": str(uuid4()), "ct": contact, "c": company, "n": "x" * 301},
                )
    finally:
        engine.dispose()

    command.downgrade(config, "0012_notification_digest_channel")
    engine = create_engine(url)
    try:
        assert "connection_requests" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.fixture
def populated(tmp_path, monkeypatch):
    url, _config = migrated_database(tmp_path, monkeypatch)
    engine = create_engine(url)
    with Session(engine) as session:
        company = add_company(session, "Acme Pay")
        contact = add_contact(session, company, "Jane Doe", "Engineering Manager", "ENGINEERING_MANAGER")
        session.commit()
        ids = (str(company.id), str(contact.id))
    engine.dispose()
    return url, ids


def test_companies_command_prints_an_explained_ranking(populated, capsys):
    url, (company_id, _contact) = populated

    assert main(["outreach", "companies", "--database-url", url]) == 0

    out = capsys.readouterr().out
    assert "COMPANY HUNTER RANKING: 1" in out and "Acme Pay" in out and company_id in out
    assert "review priority, not probability" in out
    assert "sector: YES" in out and "stack: YES" in out and "size/stage: UNKNOWN" in out


def test_weekly_prints_without_sending_by_default(populated, capsys):
    url, _ = populated

    assert main(["outreach", "weekly", "--database-url", url]) == 0

    out = capsys.readouterr().out
    assert "Company Hunter" in out and "Acme Pay" in out and "not sent" in out


def test_weekly_send_without_telegram_settings_fails_clearly(populated, capsys, monkeypatch, tmp_path):
    url, _ = populated
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # Settings also read ./.env: never let a developer's real credentials send a test message.
    monkeypatch.chdir(tmp_path)

    code = main(["outreach", "weekly", "--send", "--database-url", url])

    assert code == 1 and "Telegram is not configured" in capsys.readouterr().err


def test_connection_command_validation_and_unknown_request(populated, capsys):
    url, _ = populated

    with pytest.raises(SystemExit):
        main(["outreach", "connection", "post", str(uuid4()), "--database-url", url])
    with pytest.raises(SystemExit):
        main(["outreach", "connections", "--count", "6", "--database-url", url])
    code = main(["outreach", "connection", "sent", str(uuid4()), "--database-url", url])
    assert code == 2 and "not found" in capsys.readouterr().err


def test_company_draft_without_base_cv_fails_before_any_model_call(populated, capsys, monkeypatch, tmp_path):
    url, (company_id, _contact) = populated
    monkeypatch.chdir(tmp_path)  # no private/cv here

    code = main(["outreach", "company-draft", company_id, "--database-url", url])

    assert code == 2 and "Base CV not found" in capsys.readouterr().err


def test_find_contacts_for_a_company_without_website_stores_nothing(tmp_path, monkeypatch, capsys):
    url, _config = migrated_database(tmp_path, monkeypatch)
    engine = create_engine(url)
    with Session(engine) as session:
        company = add_company(session, "No Site", website=None, lead=False)
        session.commit()
        company_id = str(company.id)
    engine.dispose()

    assert main(["outreach", "find-contacts", company_id, "--database-url", url]) == 0

    out = capsys.readouterr().out
    assert "stored=0" in out and "no company website" in out and "LinkedIn was not contacted" in out


def test_no_command_can_send_to_a_company_or_linkedin(capsys):
    for name in ("send", "message", "connect", "invite"):
        with pytest.raises(SystemExit):
            main(["outreach", name])
    capsys.readouterr()
