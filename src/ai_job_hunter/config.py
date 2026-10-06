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
    # IANA time zone of the candidate: decides the day (and weekdays) of the Company Hunter queue.
    schedule_timezone: str = "Europe/Madrid"
    # Company boards read at the same time during a refresh (per-server limits still apply).
    fetch_workers: int = Field(default=8, ge=1, le=32)
    # Only postings published (or first seen) within this many days alert.
    notify_max_age_days: int = Field(default=3, ge=1, le=60)
    # Comma-separated job portals queried by refresh/run (empty disables portals).
    # Known: himalayas, manfred, adzuna, remoteok, remotive, jobicy, arbeitnow, fourdayweek, weworkremotely, theirstack, fantastic_jobs.
    # Adzuna needs the keys below. remoteok is off by default: applying through Remote OK requires a paid plan.
    job_portals: str = "himalayas,manfred,remotive,jobicy,adzuna,arbeitnow,fourdayweek,weworkremotely"
    # Optional Adzuna credentials (https://developer.adzuna.com); the adzuna portal is skipped without them.
    adzuna_app_id: SecretStr | None = None
    adzuna_app_key: SecretStr | None = None
    # TheirStack (https://theirstack.com) bills one credit per job returned: the key enables the
    # opt-in `theirstack` portal and the daily credit budget caps what it can spend.
    theirstack_api_key: SecretStr | None = None
    theirstack_daily_credits: int = Field(default=100, ge=1, le=5000)
    # Companies whose recent postings are always searched (any country), e.g. employers that publish
    # only on LinkedIn. Comma-separated names as TheirStack spells them ("Bizneo HR").
    theirstack_watch_companies: str = ""
    # Optional TheirStack search filters, comma-separated; empty keeps the built-in defaults
    # (countries ES, NL, CH, IE, LU; junior/mid seniority; backend/software/AI title keywords).
    theirstack_countries: str = ""
    theirstack_titles: str = ""
    theirstack_seniority: str = ""
    # Fantastic.jobs (https://fantastic.jobs): recent LinkedIn and job-board postings; one job credit per job returned.
    # Enable the opt-in `fantastic_jobs` portal by adding it to JOB_PORTALS. Filters are comma-separated; empty = defaults.
    fantastic_jobs_api_key: SecretStr | None = None
    fantastic_jobs_daily_credits: int = Field(default=70, ge=1, le=100000)
    fantastic_jobs_time_frame: str = "24h"
    fantastic_jobs_titles: str = ""
    fantastic_jobs_countries: str = ""


def get_settings() -> Settings:
    """Load settings when needed, rather than reading environment at import time."""

    return Settings()
