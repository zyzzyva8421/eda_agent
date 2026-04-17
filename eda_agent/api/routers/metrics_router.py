"""Timing / congestion query router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from eda_agent.agent.tools import execute_tool
from eda_agent.api.auth import get_current_user
from eda_agent.db.session import get_db_dependency

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/timing")
def get_timing(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
    _user: dict = Depends(get_current_user),
):
    import json

    result = execute_tool(
        "query_timing",
        {
            "design_name": design_name,
            "stage": stage,
            "run_id": run_id,
            "limit": limit,
        },
    )
    return json.loads(result)


@router.get("/congestion")
def get_congestion(
    run_id: int,
    x1: float | None = None,
    y1: float | None = None,
    x2: float | None = None,
    y2: float | None = None,
    _user: dict = Depends(get_current_user),
):
    import json

    args: dict[str, Any] = {"run_id": run_id}
    if all(v is not None for v in [x1, y1, x2, y2]):
        args.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return json.loads(execute_tool("query_congestion", args))


@router.get("/compare")
def compare(
    run_id_a: int,
    run_id_b: int,
    _user: dict = Depends(get_current_user),
):
    import json

    return json.loads(execute_tool("compare_runs", {"run_id_a": run_id_a, "run_id_b": run_id_b}))
