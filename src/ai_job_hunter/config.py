"""Application configuration loaded from environment variables or ``.env``."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by the application and database migration tooling."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://localhost:5432/ai_job_hunter"


def get_settings() -> Settings:
    """Load settings when needed, rather than reading environment at import time."""

    return Settings()
