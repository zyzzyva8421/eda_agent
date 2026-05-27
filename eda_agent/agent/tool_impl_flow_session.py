"""Implementation helpers for flow session lifecycle persistence."""

from __future__ import annotations

import datetime
import importlib.metadata as metadata
import json
import sys
import uuid
from typing import Any

from sqlalchemy import text

from eda_agent.backends.base import DesignSpec
from eda_agent.db.session import get_db


def _pkg_version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except Exception:
        return "unknown"


def create_flow_session_impl(
    design: DesignSpec,
    objective: str = "pnr",
    notes: str = "",
    *,
    get_db_fn: Any = get_db,
) -> int:
    """Create a flow session row and return its id."""
    env_snapshot = {
        "python": sys.version,
        "sqlalchemy": _pkg_version("sqlalchemy"),
        "pdk": design.pdk,
        "design": design.name,
        "captured_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    with get_db_fn() as db:
        design_row = db.execute(
            text("SELECT id FROM designs WHERE name = :name AND pdk = :pdk"),
            {"name": design.name, "pdk": design.pdk},
        ).first()
        design_id = design_row[0] if design_row else None
        if design_id is None:
            db.execute(
                text(
                    "INSERT INTO designs (name, pdk, config_path) "
                    "VALUES (:name, :pdk, :cfg)"
                ),
                {
                    "name": design.name,
                    "pdk": design.pdk,
                    "cfg": str(design.config_path),
                },
            )
            design_id = db.execute(
                text("SELECT id FROM designs WHERE name = :name AND pdk = :pdk"),
                {"name": design.name, "pdk": design.pdk},
            ).scalar()

        session_id = db.execute(
            text(
                """
                INSERT INTO flow_sessions
                    (session_uuid, design_id, objective, status, notes, env_snapshot)
                VALUES
                    (:session_uuid, :design_id, :objective, 'active', :notes, :env_snapshot)
                RETURNING id
                """
            ),
            {
                "session_uuid": str(uuid.uuid4()),
                "design_id": design_id,
                "objective": objective,
                "notes": notes,
                "env_snapshot": json.dumps(env_snapshot),
            },
        ).scalar()
        return int(session_id)


def update_flow_session_status_impl(
    session_id: int,
    status: str,
    baseline_run_id: int | None = None,
    *,
    get_db_fn: Any = get_db,
) -> None:
    """Update flow session lifecycle state (active/completed/failed)."""
    with get_db_fn() as db:
        if baseline_run_id is None:
            db.execute(
                text(
                    """
                    UPDATE flow_sessions
                    SET status = :status,
                        updated_at = now()
                    WHERE id = :sid
                    """
                ),
                {"status": status, "sid": session_id},
            )
            return

        db.execute(
            text(
                """
                UPDATE flow_sessions
                SET status = :status,
                    baseline_run_id = :baseline_run_id,
                    updated_at = now()
                WHERE id = :sid
                """
            ),
            {
                "status": status,
                "baseline_run_id": baseline_run_id,
                "sid": session_id,
            },
        )
