"""Runs router – trigger EDA stages and list run history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from eda_agent.api.auth import get_current_user
from eda_agent.agent.tools import execute_tool
from eda_agent.db.session import get_db_dependency

router = APIRouter(prefix="/runs", tags=["runs"])


class RunStageRequest(BaseModel):
    backend: str
    stage: str
    design_name: str
    design_config: str
    pdk: str
    params: dict[str, Any] = {}


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
def trigger_run(
    req: RunStageRequest,
    _user: dict = Depends(get_current_user),
):
    """Trigger a backend stage asynchronously (runs inline for now)."""
    result_json = execute_tool(
        "run_eda_stage",
        {
            "backend": req.backend,
            "stage": req.stage,
            "design_name": req.design_name,
            "design_config": req.design_config,
            "pdk": req.pdk,
            "params": req.params,
        },
    )
    import json
    return json.loads(result_json)


@router.get("/")
def list_runs(
    design_name: str | None = None,
    stage: str | None = None,
    backend: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if design_name:
        conditions.append("d.name = :design_name")
        params["design_name"] = design_name
    if stage:
        conditions.append("r.stage = :stage")
        params["stage"] = stage
    if backend:
        conditions.append("b.name = :backend")
        params["backend"] = backend

    where = " AND ".join(conditions)
    rows = db.execute(
        text(
            f"""
            SELECT r.id, r.run_uuid, r.stage, r.status, r.params,
                   r.started_at, r.finished_at, r.error_message,
                   b.name AS backend, d.name AS design, d.pdk
            FROM runs r
            JOIN backends b ON b.id = r.backend_id
            JOIN designs  d ON d.id = r.design_id
            WHERE {where}
            ORDER BY r.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().fetchall()
    return [dict(r) for r in rows]


@router.get("/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    row = db.execute(
        text(
            """
            SELECT r.*, b.name AS backend, d.name AS design, d.pdk
            FROM runs r
            JOIN backends b ON b.id = r.backend_id
            JOIN designs  d ON d.id = r.design_id
            WHERE r.id = :run_id
            """
        ),
        {"run_id": run_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return dict(row)
