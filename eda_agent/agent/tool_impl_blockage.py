"""Implementation helpers for placement blockage injection."""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import text

from eda_agent.backends import get_backend
from eda_agent.db.session import get_db


def add_placement_blockage_impl(
    run_id: int,
    blockages: list[dict[str, Any]],
    workdir: str | None = None,
    stage: str = "place",
    *,
    get_db_fn: Any = get_db,
    get_backend_fn: Callable[[str], Any] = get_backend,
) -> dict[str, Any]:
    """Apply placement blockages to an Innovus run context and persist metadata."""
    with get_db_fn() as db:
        run_row = db.execute(
            text(
                """
                SELECT r.id AS run_id, r.params, r.stage, b.name AS backend, d.name AS design_name
                FROM runs r
                JOIN designs d ON d.id = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE r.id = :rid
                """
            ),
            {"rid": run_id},
        ).mappings().first()

        if not run_row:
            return {"error": f"Run {run_id} not found"}

        backend_name = str(run_row["backend"]).lower()
        if backend_name != "innovus":
            return {
                "error": (
                    "add_placement_blockage supports only innovus backend, "
                    f"got '{backend_name}'"
                )
            }

        backend = get_backend_fn(backend_name)
        if not hasattr(backend, "add_blockage_to_design_state"):
            return {
                "error": "Selected backend does not support placement blockage injection"
            }

        details = backend.add_blockage_to_design_state(  # type: ignore[attr-defined]
            design_name=str(run_row["design_name"]),
            blockage_specs=blockages,
            workdir=workdir,
            stage=stage,
        )

        existing_params = run_row["params"] if isinstance(run_row["params"], dict) else {}
        if isinstance(run_row["params"], str):
            try:
                existing_params = json.loads(run_row["params"])
            except json.JSONDecodeError:
                existing_params = {}
        blockage_history = list(existing_params.get("placement_blockages", []))
        blockage_history.extend(blockages)

        updated_params = dict(existing_params)
        updated_params["placement_blockages"] = blockage_history
        db.execute(
            text("UPDATE runs SET params = :params WHERE id = :rid"),
            {"rid": run_id, "params": json.dumps(updated_params)},
        )

    return {
        "run_id": run_id,
        "status": "success",
        "backend": "innovus",
        "applied_blockages": len(blockages),
        "blockages": blockages,
        "details": details,
    }
