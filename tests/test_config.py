from ai_job_hunter.config import Settings


def test_settings_accept_database_url_override() -> None:
    settings = Settings(database_url="postgresql+psycopg://example/test_db")

    assert settings.database_url == "postgresql+psycopg://example/test_db"


def test_settings_read_database_url_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://env/test_db")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://env/test_db"


def test_settings_have_a_local_postgresql_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.startswith("postgresql+psycopg://")
