"""Implementation helpers for multi-agent tool operations."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def run_multi_agent_cycle_tool_impl(
    *,
    objective: str,
    session_id: int | None = None,
    run_id: int | None = None,
    constraints: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    agents: list[str] | None = None,
    execute_experiment: bool = False,
    experiment_request: dict[str, Any] | None = None,
    run_eda_stage_fn: Callable[..., dict[str, Any]],
    resolve_identity_fn: Callable[..., tuple[str, str]],
    record_decision_trace_fn: Callable[..., None],
) -> dict[str, Any]:
    """Execute one multi-agent cycle and optionally run an experiment stage."""
    from eda_agent.agent.planner import Planner

    planner = Planner()
    cycle = planner.run_multi_agent_cycle(
        objective=objective,
        session_id=session_id,
        run_id=run_id,
        constraints=constraints,
        inputs=inputs,
        agents=agents,
    )

    result: dict[str, Any] = {"multi_agent": cycle}
    if not execute_experiment:
        return result

    gate = (cycle or {}).get("gate") or {}
    if gate.get("status") != "auto_execute":
        result["experiment_execution"] = {
            "status": "blocked",
            "reason": gate.get("reason", "needs approval"),
        }
        return result

    if not experiment_request:
        result["experiment_execution"] = {
            "status": "skipped",
            "reason": "experiment_request not provided",
        }
        return result

    exp_args = dict(experiment_request)
    backend = str(exp_args.get("backend") or "")
    if not backend:
        return {
            **result,
            "experiment_execution": {
                "status": "error",
                "error": "experiment_request.backend is required",
            },
        }

    try:
        design_config, pdk = resolve_identity_fn(
            backend=backend,
            design_config=exp_args.get("design_config"),
            pdk=exp_args.get("pdk"),
            innovus_workdir=exp_args.get("innovus_workdir"),
            tech_profile=exp_args.get("tech_profile"),
        )
    except Exception as exc:
        result["experiment_execution"] = {
            "status": "error",
            "error": str(exc),
        }
        return result

    run_context = dict(exp_args.get("run_context") or {})
    if session_id is not None:
        run_context.setdefault("session_id", session_id)
    run_context.setdefault("stage_seq", 1)
    run_context.setdefault("variant_tag", "multi_agent_experiment")
    run_context.setdefault("rerun_reason", "run_multi_agent_cycle")
    run_context.setdefault("is_baseline", False)
    run_context.setdefault("is_selected", False)

    try:
        run_result = run_eda_stage_fn(
            backend=backend,
            stage=str(exp_args.get("stage") or ""),
            design_name=str(exp_args.get("design_name") or ""),
            design_config=design_config,
            pdk=pdk,
            params=exp_args.get("params") or {},
            run_context=run_context,
            innovus_workdir=exp_args.get("innovus_workdir"),
            tech_profile=exp_args.get("tech_profile"),
        )
    except Exception as exc:
        result["experiment_execution"] = {
            "status": "error",
            "error": str(exc),
        }
        return result

    result["experiment_execution"] = {
        "status": "success" if run_result.get("status") == "success" else "failed",
        "result": run_result,
    }

    # Persist multi-agent decision trace for replayability when lineage ids exist.
    target_run_id = run_result.get("run_id")
    if (
        session_id is not None
        and run_id is not None
        and isinstance(target_run_id, int)
    ):
        try:
            gate = (cycle or {}).get("gate") or {}
            record_decision_trace_fn(
                session_id=session_id,
                source_run_id=run_id,
                target_run_id=target_run_id,
                llm_reason=(
                    "multi_agent_cycle executed experiment "
                    f"{backend}:{exp_args.get('stage', '')}"
                ),
                llm_reason_structured={
                    "kind": "multi_agent_cycle",
                    "objective": objective,
                    "gate_status": gate.get("status"),
                    "agents": cycle.get("agents", []),
                    "execute_experiment": True,
                    "multi_agent_contract": {
                        "contract_version": cycle.get("contract_version", "v1"),
                        "status_summary": cycle.get("status_summary", {}),
                        "decision_view": cycle.get("decision_view", {}),
                        "gate": cycle.get("gate", {}),
                    },
                    "experiment": {
                        "backend": backend,
                        "stage": exp_args.get("stage"),
                        "design_name": exp_args.get("design_name"),
                    },
                },
                human_approved=bool(gate.get("status") == "needs_approval"),
            )
        except Exception:
            logger.warning("Failed to persist multi-agent decision_trace", exc_info=True)

    return result
