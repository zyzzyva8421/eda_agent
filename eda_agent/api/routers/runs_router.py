"""Runs router – trigger EDA stages and list run history."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from eda_agent.api.auth import get_current_user
from eda_agent.agent.tools import _create_flow_session, execute_tool
from eda_agent.backends.base import DesignSpec
from eda_agent.db.repository import EDAQueryRepository
from eda_agent.db.session import get_db_dependency

logger = logging.getLogger(__name__)
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
    design = DesignSpec(
        name=req.design_name,
        config_path=req.design_config,
        pdk=req.pdk,
    )
    session_id = _create_flow_session(
        design,
        objective=str((req.params or {}).get("_objective", "pnr")),
        notes=f"single_stage:{req.stage}",
    )

    result_json = execute_tool(
        "run_eda_stage",
        {
            "backend": req.backend,
            "stage": req.stage,
            "design_name": req.design_name,
            "design_config": req.design_config,
            "pdk": req.pdk,
            "params": req.params,
            "run_context": {
                "session_id": session_id,
                "stage_seq": 1,
                "variant_tag": "baseline",
                "rerun_reason": f"single_stage:{req.stage}",
                "is_baseline": True,
                "is_selected": False,
            },
        },
    )
    data = json.loads(result_json)
    error_text = ""
    if isinstance(data, dict):
        error_text = str(data.get("error") or "").strip()
    if isinstance(data, dict) and error_text:
        logger.error("run_eda_stage error: %s", error_text)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while running the EDA stage.",
        )
    return data


@router.get("/")
def list_runs(
    design_name: str | None = None,
    stage: str | None = None,
    backend: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    return EDAQueryRepository.list_runs(
        db, design_name=design_name, stage=stage, backend=backend, limit=limit
    )


@router.get("/sessions/{session_id}/trace")
def get_session_trace(
    session_id: int,
    stage: str | None = None,
    from_seq: int | None = None,
    to_seq: int | None = None,
    human_approved: bool | None = None,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    trace = EDAQueryRepository.get_session_trace(
        db,
        session_id,
        stage=stage,
        from_seq=from_seq,
        to_seq=to_seq,
        human_approved=human_approved,
    )
    if isinstance(trace, dict) and "error" in trace:
        raise HTTPException(status_code=404, detail=trace["error"])
    return trace


@router.get("/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    row = EDAQueryRepository.get_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return row
