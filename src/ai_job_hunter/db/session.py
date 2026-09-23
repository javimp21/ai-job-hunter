"""SQLAlchemy engine and session factory construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_job_hunter.config import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    """Create an engine using the configured PostgreSQL connection string."""

    active_settings = settings or get_settings()
    return create_engine(active_settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions bound to an application database engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
