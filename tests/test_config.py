from pathlib import Path

from ai_job_hunter.config import Settings


def test_settings_accept_database_url_override() -> None:
    settings = Settings(database_url="postgresql+psycopg://example/test_db")

    assert settings.database_url == "postgresql+psycopg://example/test_db"


def test_settings_read_database_url_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://env/test_db")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://env/test_db"


def test_settings_load_and_redact_typesafe_key_from_env_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_API_KEY=fake-test-key\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.typesafe_api_key is not None
    assert settings.typesafe_api_key.get_secret_value() == "fake-test-key"
    assert "fake-test-key" not in repr(settings)


def test_settings_have_a_local_postgresql_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.startswith("postgresql+psycopg://")
