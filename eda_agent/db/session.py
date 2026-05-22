"""Database session factory and helper utilities."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from eda_agent.config import settings
from eda_agent.db.schema import Base

_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    echo=settings.log_level == "DEBUG",
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=_engine, autocommit=False, autoflush=False
)


def get_engine():
    return _engine


def create_all_tables() -> None:
    """Create all tables (and PostGIS extension) in the database."""
    with _engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()
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
    """FastAPI dependency that yields a session per request.

    Commits on success, rolls back on exception — consistent with
    :func:`get_db` behaviour so callers do not need to manage transactions.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
