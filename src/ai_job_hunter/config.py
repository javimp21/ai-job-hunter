"""Application configuration loaded from environment variables or ``.env``."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by the application and database migration tooling."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://localhost:5432/ai_job_hunter"
    typesafe_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    notify_review_min_priority: int = Field(default=70, ge=0, le=100)
    # Only postings published (or first seen) within this many days alert.
    notify_max_age_days: int = Field(default=3, ge=1, le=60)
    # Comma-separated job portals queried by refresh/run (empty disables portals).
    job_portals: str = "himalayas"


def get_settings() -> Settings:
    """Load settings when needed, rather than reading environment at import time."""

    return Settings()
