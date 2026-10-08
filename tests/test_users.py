import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from ai_job_hunter.models.user import User, UserProfile
from ai_job_hunter.services.users import ensure_owner, get_owner, import_owner_profile, load_profile, save_profile
from tests.test_candidate_prefilter import make_config


def test_migration_0015_creates_users_and_profiles_and_can_be_undone(tmp_path: Path, monkeypatch, keep_logging_state) -> None:
    repo_root = Path(__file__).parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'users.sqlite3').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {"users", "user_profiles"} <= set(inspector.get_table_names())
    assert {"telegram_chat_id", "is_owner", "status", "consent_at", "trial_ends_at"} <= {
        column["name"] for column in inspector.get_columns("users")
    }
    command.downgrade(config, "0014_company_hunter")
    assert "users" not in inspect(create_engine(database_url)).get_table_names()


def test_there_is_one_owner_and_the_profile_round_trips(db_session) -> None:
    first = ensure_owner(db_session)
    again = ensure_owner(db_session)
    assert first.id == again.id and get_owner(db_session).id == first.id and first.is_owner

    config = make_config(preferences={"sector": "finance"})
    profile, changed = save_profile(db_session, first, config)
    assert changed and profile.sector == "finance"
    _, changed_again = save_profile(db_session, first, config)
    assert not changed_again
    assert load_profile(db_session, first) == config

    other = make_config(preferences={"sector": "software"})
    _, changed_other = save_profile(db_session, first, other)
    assert changed_other and load_profile(db_session, first).preferences.sector == "software"
    assert db_session.scalar(select(UserProfile.id).where(UserProfile.user_id == first.id)) == profile.id


def test_a_telegram_chat_belongs_to_one_user(db_session) -> None:
    db_session.add_all([User(telegram_chat_id="42", language="es", timezone="Europe/Madrid", status="ACTIVE", is_owner=False)])
    db_session.flush()
    db_session.add(User(telegram_chat_id="42", language="en", timezone="Europe/Dublin", status="ACTIVE", is_owner=False))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_importing_the_owner_file_is_idempotent(db_session, tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(make_config().model_dump(mode="json")), encoding="utf-8")

    owner, profile, changed = import_owner_profile(db_session, path)
    assert changed
    owner_again, profile_again, changed_again = import_owner_profile(db_session, path)
    assert (owner_again.id, profile_again.id, changed_again) == (owner.id, profile.id, False)


def _alembic(tmp_path: Path, monkeypatch, name: str):
    repo_root = Path(__file__).parents[1]
    url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    return url, config


def _insert(engine, table_name: str, **values) -> None:
    import sqlalchemy as sa

    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(table.insert().values(**values))


def test_migration_0017_fills_user_id_with_the_owner_and_leaves_a_fresh_database_alone(
    tmp_path: Path, monkeypatch, keep_logging_state
) -> None:
    from uuid import uuid4

    import sqlalchemy as sa

    url, config = _alembic(tmp_path, monkeypatch, "owned.sqlite3")
    command.upgrade(config, "0016_job_feedback_notes")
    engine = create_engine(url)
    owner_id, company_id, job_id = uuid4().hex, uuid4().hex, uuid4().hex  # SQLite keeps uuids as 32 hex characters
    _insert(engine, "users", id=owner_id, language="es", timezone="Europe/Madrid", status="ACTIVE", is_owner=True)
    _insert(engine, "companies", id=company_id, name="Acme")
    _insert(engine, "jobs", id=job_id, company_id=company_id, title="Backend Engineer")
    _insert(engine, "job_reviews", id=uuid4().hex, job_id=job_id, state="SAVED")
    _insert(engine, "job_feedback_notes", id=uuid4().hex, job_id=job_id, text="ok")

    command.upgrade(config, "0017_user_id_columns")

    with engine.connect() as connection:
        for table in ("job_reviews", "job_feedback_notes"):
            assert connection.execute(sa.text(f"SELECT user_id FROM {table}")).scalar_one() is not None
    assert "user_id" in {c["name"] for c in inspect(engine).get_columns("job_evaluations")}

    command.downgrade(config, "0016_job_feedback_notes")
    assert "user_id" not in {c["name"] for c in inspect(create_engine(url)).get_columns("job_reviews")}

    fresh_url, fresh_config = _alembic(tmp_path, monkeypatch, "fresh.sqlite3")
    command.upgrade(fresh_config, "head")
    assert "user_id" in {c["name"] for c in inspect(create_engine(fresh_url)).get_columns("report_deliveries")}


def test_migration_0019_makes_uniqueness_per_user_and_can_be_undone(tmp_path: Path, monkeypatch, keep_logging_state) -> None:
    url, config = _alembic(tmp_path, monkeypatch, "unique.sqlite3")
    command.upgrade(config, "head")
    names = {index["name"] for index in inspect(create_engine(url)).get_indexes("job_reviews")}
    assert {"uq_job_reviews_job_user", "uq_job_reviews_job_unowned"} <= names

    command.downgrade(config, "0018_user_id_backfill")
    inspector = inspect(create_engine(url))
    assert "uq_job_reviews_job_user" not in {index["name"] for index in inspector.get_indexes("job_reviews")}
    assert any(c["name"] == "uq_job_reviews_job_id" for c in inspector.get_unique_constraints("job_reviews"))
