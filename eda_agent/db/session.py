"""Database session factory and helper utilities."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
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


def is_postgresql() -> bool:
    """Return True when the configured database engine targets PostgreSQL."""
    return _engine.dialect.name == "postgresql"


@lru_cache(maxsize=1)
def supports_postgresql_jsonb() -> bool:
    """Return True when the PostgreSQL server version supports JSONB (>= 9.4)."""
    if not is_postgresql():
        return False

    ver_info = getattr(_engine.dialect, "server_version_info", None)
    if isinstance(ver_info, tuple) and len(ver_info) >= 2:
        return (int(ver_info[0]), int(ver_info[1])) >= (9, 4)

    try:
        with _engine.connect() as conn:
            ver_num = conn.execute(text("SHOW server_version_num")).scalar()
        return int(ver_num) >= 90400
    except Exception:
        return False


def create_all_tables() -> None:
    """Create all tables (and PostGIS extension) in the database."""
    with _engine.connect() as conn:
        if settings.enable_postgis:
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
