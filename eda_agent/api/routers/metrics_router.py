"""Timing / congestion / utilization / power query router."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from eda_agent.agent.tools import execute_tool
from eda_agent.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metrics", tags=["metrics"])


def _safe_result(raw: str) -> Any:
    """Parse tool JSON and raise 500 if the tool returned an error,
    without leaking internal exception details to the client."""
    data = json.loads(raw)
    if isinstance(data, dict) and "error" in data:
        logger.error("Tool error: %s", data["error"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while executing the requested operation.",
        )
    return data


@router.get("/timing")
def get_timing(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
    _user: dict = Depends(get_current_user),
):
    result = execute_tool(
        "query_timing",
        {
            "design_name": design_name,
            "stage": stage,
            "run_id": run_id,
            "limit": limit,
        },
    )
    return _safe_result(result)


@router.get("/congestion")
def get_congestion(
    run_id: int,
    x1: float | None = None,
    y1: float | None = None,
    x2: float | None = None,
    y2: float | None = None,
    _user: dict = Depends(get_current_user),
):
    args: dict[str, Any] = {"run_id": run_id}
    if all(v is not None for v in [x1, y1, x2, y2]):
        args.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return _safe_result(execute_tool("query_congestion", args))


@router.get("/utilization")
def get_utilization(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
    _user: dict = Depends(get_current_user),
):
    """Query design-area and cell-utilisation metrics."""
    return _safe_result(
        execute_tool(
            "query_utilization",
            {"design_name": design_name, "stage": stage, "run_id": run_id, "limit": limit},
        )
    )


@router.get("/power")
def get_power(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
    _user: dict = Depends(get_current_user),
):
    """Query power breakdown metrics."""
    return _safe_result(
        execute_tool(
            "query_power",
            {"design_name": design_name, "stage": stage, "run_id": run_id, "limit": limit},
        )
    )


@router.get("/compare")
def compare(
    run_id_a: int,
    run_id_b: int,
    _user: dict = Depends(get_current_user),
):
    return _safe_result(
        execute_tool("compare_runs", {"run_id_a": run_id_a, "run_id_b": run_id_b})
    )
