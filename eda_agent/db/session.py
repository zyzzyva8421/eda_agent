"""Database session factory and helper utilities."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from eda_agent.config import settings
from eda_agent.db.schema import Base

logger = logging.getLogger(__name__)

_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.log_level == "DEBUG",
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=_engine, autocommit=False, autoflush=False
)


def get_engine():
    return _engine


def _enable_postgis_if_available() -> None:
    """Enable PostGIS extension when running on PostgreSQL with extension available."""
    if _engine.dialect.name != "postgresql":
        return

    with _engine.connect() as conn:
        is_available = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_available_extensions
                    WHERE name = 'postgis'
                )
                """
            )
        ).scalar_one()

        if not is_available:
            logger.info("PostGIS extension is not available on this PostgreSQL instance.")
            return

        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()


def create_all_tables() -> None:
    """Create all tables in the database."""
    _enable_postgis_if_available()
    Base.metadata.create_all(bind=_engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context-manager that yields a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_dependency():
    """FastAPI dependency that yields a session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
