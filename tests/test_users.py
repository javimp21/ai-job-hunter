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
