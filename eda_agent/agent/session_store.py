"""Shared persistence layer for agent sessions.

Both the CLI REPL and the HTTP ``/agent/chat`` route use this module so they
read and write the same ``agent_sessions`` rows.  The store gracefully
degrades when no database is available (so CLI continues to work for users
without a configured PostgreSQL backend); in that case loads return an
empty :class:`AgentMemory` and saves are silently skipped.

Storage layout
--------------
A session row contains:

* ``messages``  – list of OpenAI-compatible chat messages (L1 short-term)
* ``scratchpad`` – JSON object with a ``context`` sub-dict for durable
  facts (design_name / pdk / config_path / last_run_id …).  Volatile keys
  (anything prefixed with ``_``) are *not* persisted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg2.extras import Json
from sqlalchemy import text
from sqlalchemy.orm import Session

from eda_agent.agent.memory import AgentMemory

logger = logging.getLogger(__name__)

# Hard cap on the size of a persisted session payload (messages JSON).  When
# exceeded we drop the oldest message pairs until we fit – see
# :meth:`AgentMemory.shrink_to_byte_budget`.
MAX_SESSION_BYTES = 512 * 1024


def _rollback_quietly(db: Session | None) -> None:
    if db is None:
        return
    try:
        db.rollback()
    except Exception:
        pass


def _is_missing_column_error(exc: Exception, column: str) -> bool:
    text = str(exc).lower()
    return column.lower() in text and ("does not exist" in text or "undefinedcolumn" in text)


@dataclass
class SessionInfo:
    session_id: str
    username: str
    updated_at: datetime
    message_count: int


# ---------------------------------------------------------------------------
# Core load / save
# ---------------------------------------------------------------------------


def load_session(session_id: str, db: Session | None) -> AgentMemory:
    """Load a session into a fresh :class:`AgentMemory`.

    Returns a brand-new empty memory when ``db`` is ``None``, when the
    session does not exist, or when the database lookup fails.
    """
    if db is None:
        return AgentMemory()
    used_legacy_layout = False
    try:
        row = (
            db.execute(
                text(
                    "SELECT messages, scratchpad FROM agent_sessions "
                    "WHERE session_id = :sid"
                ),
                {"sid": session_id},
            )
            .mappings()
            .first()
        )
    except Exception as exc:  # pragma: no cover – DB unavailable
        _rollback_quietly(db)
        if not _is_missing_column_error(exc, "scratchpad"):
            logger.debug("load_session(%s) failed", session_id, exc_info=True)
            return AgentMemory()
        # Backward compatibility: old schema has only `messages`.
        used_legacy_layout = True
        try:
            row = (
                db.execute(
                    text(
                        "SELECT messages FROM agent_sessions "
                        "WHERE session_id = :sid"
                    ),
                    {"sid": session_id},
                )
                .mappings()
                .first()
            )
        except Exception:  # pragma: no cover – DB unavailable
            _rollback_quietly(db)
            logger.debug("load_session(%s) legacy fallback failed", session_id, exc_info=True)
            return AgentMemory()

    if not row:
        return AgentMemory()

    raw_messages = row.get("messages") or []
    raw_scratchpad = {} if used_legacy_layout else (row.get("scratchpad") or {})
    if isinstance(raw_messages, str):
        # Legacy / defensive path: tolerate accidentally stringified JSON.
        import json

        try:
            raw_messages = json.loads(raw_messages)
        except Exception:
            raw_messages = []
    if isinstance(raw_scratchpad, str):
        import json

        try:
            raw_scratchpad = json.loads(raw_scratchpad)
        except Exception:
            raw_scratchpad = {}
    return AgentMemory.from_dict(
        {"messages": raw_messages, "scratchpad": raw_scratchpad}
    )


def save_session(
    session_id: str,
    username: str,
    memory: AgentMemory,
    db: Session | None,
) -> None:
    """Upsert ``memory`` into the DB.  No-op when ``db`` is ``None``."""
    if db is None:
        return
    did_fallback = False
    try:
        # Enforce a per-session size cap by dropping oldest message pairs
        # until the serialised payload fits.
        memory.shrink_to_byte_budget(MAX_SESSION_BYTES)
        payload = memory.to_dict(persist_internal=False)
        db.execute(
            text(
                """
                INSERT INTO agent_sessions
                    (session_id, username, messages, scratchpad, updated_at)
                VALUES (:sid, :uname, :msgs, :scratch, now())
                ON CONFLICT (session_id) DO UPDATE
                  SET messages   = EXCLUDED.messages,
                      scratchpad = EXCLUDED.scratchpad,
                      updated_at = now()
                """
            ),
            {
                "sid": session_id,
                "uname": username,
                "msgs": Json(payload["messages"]),
                "scratch": Json(payload["scratchpad"]),
            },
        )
        db.commit()
    except Exception as exc:  # pragma: no cover – DB unavailable
        _rollback_quietly(db)
        if _is_missing_column_error(exc, "scratchpad"):
            did_fallback = True
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO agent_sessions
                            (session_id, username, messages, updated_at)
                        VALUES (:sid, :uname, :msgs, now())
                        ON CONFLICT (session_id) DO UPDATE
                          SET messages   = EXCLUDED.messages,
                              updated_at = now()
                        """
                    ),
                    {
                        "sid": session_id,
                        "uname": username,
                        "msgs": Json(payload["messages"]),
                    },
                )
                db.commit()
                return
            except Exception:  # pragma: no cover – DB unavailable
                _rollback_quietly(db)
                logger.debug("save_session(%s) legacy fallback failed", session_id, exc_info=True)
                return
        logger.debug("save_session(%s) failed", session_id, exc_info=True)
    finally:
        if did_fallback:
            logger.debug("save_session(%s) used legacy layout fallback", session_id)


def clear_session(session_id: str, db: Session | None) -> None:
    """Delete a session row (used by REPL ``forget`` and DELETE endpoint)."""
    if db is None:
        return
    try:
        db.execute(
            text("DELETE FROM agent_sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )
        db.commit()
    except Exception:  # pragma: no cover
        _rollback_quietly(db)
        logger.debug("clear_session(%s) failed", session_id, exc_info=True)


def list_sessions(
    username: str | None,
    db: Session | None,
    limit: int = 20,
) -> list[SessionInfo]:
    """Return the most recently updated sessions for *username*.

    When ``username`` is ``None`` all sessions are returned.  Used by the
    REPL ``sessions`` command.
    """
    if db is None:
        return []
    try:
        if username is None:
            rows = db.execute(
                text(
                    """
                    SELECT session_id, username, updated_at,
                           jsonb_array_length(messages) AS msg_count
                    FROM agent_sessions
                    ORDER BY updated_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            ).fetchall()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT session_id, username, updated_at,
                           jsonb_array_length(messages) AS msg_count
                    FROM agent_sessions
                    WHERE username = :uname
                    ORDER BY updated_at DESC
                    LIMIT :lim
                    """
                ),
                {"uname": username, "lim": limit},
            ).fetchall()
    except Exception:  # pragma: no cover
        _rollback_quietly(db)
        logger.debug("list_sessions failed", exc_info=True)
        return []

    return [
        SessionInfo(
            session_id=r[0],
            username=r[1] or "",
            updated_at=r[2],
            message_count=int(r[3] or 0),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def open_db() -> Any | None:
    """Open a short-lived SQLAlchemy session, or ``None`` when unreachable.

    Used by the CLI which is not running inside a FastAPI request scope.
    Returns a :class:`sqlalchemy.orm.Session` ready to use (caller is
    responsible for calling ``close()``).  The actual connect happens
    lazily on first ``execute`` so a return value here does *not*
    guarantee reachability – the individual ``load_session`` /
    ``save_session`` helpers above always swallow errors.
    """
    try:
        from eda_agent.db.session import SessionLocal

        return SessionLocal()
    except Exception:  # pragma: no cover
        logger.debug("open_db failed", exc_info=True)
        return None


def default_cli_session_id(username: str | None = None) -> str:
    """Return the default session id used by the CLI."""
    import getpass
    import os

    name = username or os.environ.get("USER") or os.environ.get("USERNAME")
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = "anon"
    return f"cli-{name}-default"
