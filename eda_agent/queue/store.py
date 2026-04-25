"""SQLite-backed job store for the EDA Agent async task queue.

Each submitted EDA stage execution becomes a :class:`Job` record in a local
SQLite database (``~/.eda_agent/jobs.db`` by default).  The store is
designed to be safe for concurrent access by a single worker process and
multiple reader processes (e.g. the CLI checking status) by using SQLite's
WAL journal mode with a write timeout.

Schema
------
jobs(
    job_id        TEXT PRIMARY KEY,
    backend       TEXT,
    stage         TEXT,
    design_name   TEXT,
    design_config TEXT,
    pdk           TEXT,
    params        TEXT,       -- JSON object
    status        TEXT,       -- pending | running | success | failed | cancelled
    run_db_id     INTEGER,    -- PostgreSQL run PK (set after execution)
    log_path      TEXT,       -- Path to the ORFS make log file
    error_message TEXT,
    worker_pid    INTEGER,
    created_at    TEXT,       -- ISO-8601 with timezone
    started_at    TEXT,
    finished_at   TEXT
)
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Generator

_DEFAULT_DB_PATH: Path = Path.home() / ".eda_agent" / "jobs.db"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """In-memory representation of a queued EDA job."""

    job_id: str
    backend: str
    stage: str
    design_name: str
    design_config: str
    pdk: str
    params: dict[str, Any]
    status: JobStatus
    run_db_id: int | None = None
    log_path: str | None = None
    error_message: str = ""
    worker_pid: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


# ---------------------------------------------------------------------------
# JobStore
# ---------------------------------------------------------------------------


class JobStore:
    """Persistent SQLite-backed job queue."""

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id        TEXT PRIMARY KEY,
            backend       TEXT    NOT NULL,
            stage         TEXT    NOT NULL,
            design_name   TEXT    NOT NULL,
            design_config TEXT    NOT NULL,
            pdk           TEXT    NOT NULL,
            params        TEXT    NOT NULL DEFAULT '{}',
            status        TEXT    NOT NULL DEFAULT 'pending',
            run_db_id     INTEGER,
            log_path      TEXT,
            error_message TEXT    NOT NULL DEFAULT '',
            worker_pid    INTEGER,
            created_at    TEXT    NOT NULL,
            started_at    TEXT,
            finished_at   TEXT
        )
    """

    def __init__(self, db_path: Path | None = None) -> None:
        # Resolve default at call time so tests can patch _DEFAULT_DB_PATH.
        self._db_path = db_path if db_path is not None else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Connection management (autocommit; transactions managed explicitly)
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Open a connection in autocommit mode (isolation_level=None)."""
        conn = sqlite3.connect(str(self._db_path), timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(self._CREATE_TABLE)

    # ------------------------------------------------------------------
    # Row → Job conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            backend=row["backend"],
            stage=row["stage"],
            design_name=row["design_name"],
            design_config=row["design_config"],
            pdk=row["pdk"],
            params=json.loads(row["params"] or "{}"),
            status=JobStatus(row["status"]),
            run_db_id=row["run_db_id"],
            log_path=row["log_path"],
            error_message=row["error_message"] or "",
            worker_pid=row["worker_pid"],
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            started_at=_parse_dt(row["started_at"]),
            finished_at=_parse_dt(row["finished_at"]),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        backend: str,
        stage: str,
        design_name: str,
        design_config: str,
        pdk: str,
        params: dict[str, Any] | None = None,
    ) -> Job:
        """Insert a new *pending* job and return it."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs
                    (job_id, backend, stage, design_name, design_config, pdk,
                     params, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    job_id,
                    backend,
                    stage,
                    design_name,
                    design_config,
                    pdk,
                    json.dumps(params or {}),
                    _fmt_dt(now),
                ),
            )
        return Job(
            job_id=job_id,
            backend=backend,
            stage=stage,
            design_name=design_name,
            design_config=design_config,
            pdk=pdk,
            params=params or {},
            status=JobStatus.PENDING,
            created_at=now,
        )

    def get_job(self, job_id: str) -> Job | None:
        """Return the :class:`Job` with the given *job_id*, or ``None``."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, status: JobStatus | None = None) -> list[Job]:
        """Return all jobs, optionally filtered by *status*, newest first."""
        with self._conn() as conn:
            if status is not None:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    # ------------------------------------------------------------------
    # Worker-facing mutations
    # ------------------------------------------------------------------

    def claim_pending_job(self) -> Job | None:
        """Atomically pick the oldest *pending* job and mark it *running*.

        Uses ``BEGIN IMMEDIATE`` to prevent two worker processes from
        claiming the same job simultaneously.  Returns ``None`` when the
        queue is empty.
        """
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status = 'pending'"
                    " ORDER BY created_at ASC LIMIT 1"
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return None
                now = _fmt_dt(datetime.now(timezone.utc))
                conn.execute(
                    "UPDATE jobs SET status='running', started_at=?, worker_pid=?"
                    " WHERE job_id=?",
                    (now, os.getpid(), row["job_id"]),
                )
                job_id: str = row["job_id"]
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_job(job_id)

    def mark_done(
        self,
        job_id: str,
        *,
        status: JobStatus,
        run_db_id: int | None = None,
        log_path: str | None = None,
        error_message: str = "",
    ) -> None:
        """Transition a *running* job to *success* or *failed*."""
        now = _fmt_dt(datetime.now(timezone.utc))
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE jobs
                   SET status = ?, run_db_id = ?, log_path = ?,
                       error_message = ?, finished_at = ?
                 WHERE job_id = ?
                """,
                (status.value, run_db_id, log_path, error_message, now, job_id),
            )

    def cancel_job(self, job_id: str) -> bool:
        """Mark a *pending* job as *cancelled*.

        Returns ``True`` if the job was found and was still pending.
        Already-running jobs cannot be cancelled this way.
        """
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='cancelled'"
                " WHERE job_id=? AND status='pending'",
                (job_id,),
            )
        return cur.rowcount > 0
