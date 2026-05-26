"""Implementation helpers for stage and sync-flow execution tools."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Callable

from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec

logger = logging.getLogger(__name__)


def run_eda_stage_impl(
    *,
    backend: str,
    stage: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    params: dict[str, Any] | None = None,
    run_context: dict[str, Any] | None = None,
    resolve_identity_fn: Callable[..., tuple[str, str]],
    save_run_and_parse_fn: Callable[..., int],
    record_stage_outcome_fn: Callable[..., None],
) -> dict[str, Any]:
    # 对于 innovus，可以从 settings 或别名参数自动获取配置
    if not backend:
        if stage in (
            "place",
            "cts",
            "route",
            "floorplan",
            "powerplan",
            "prects",
            "postcts",
            "postroute",
            "signoff",
        ):
            backend = "innovus"
        else:
            backend = "orfs"

    design_config, pdk = resolve_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    be = get_backend(backend)
    design = DesignSpec(
        name=design_name,
        config_path=Path(design_config),
        pdk=pdk,
    )
    result = be.run_stage(stage, design, params or {})

    # Atomically persist run + ingest reports (single transaction)
    run_db_id = save_run_and_parse_fn(result, design, backend=be, run_context=run_context)

    root_cause_inference_id = None
    if run_context:
        root_cause_inference_id = run_context.get("root_cause_inference_id")

    # Best-effort stage snapshot for reproducibility.
    try:
        record_stage_outcome_fn(
            run_db_id,
            stage,
            result,
            root_cause_inference_id=root_cause_inference_id,
        )
    except Exception:
        logger.warning("Failed to persist stage_outcome for run %d", run_db_id)

    # Archive the run data to Parquet (best-effort; never fails the main flow)
    if result.status.value == "success":
        try:
            from eda_agent.db.archiver import archive_run

            archive_run(run_db_id)
        except Exception:
            logger.warning("Parquet archival failed for run %d", run_db_id)

    return {
        "run_id": run_db_id,
        "run_uuid": result.run_id,
        "status": result.status.value,
        "stage": stage,
        "backend": backend,
        "design_name": design_name,
        "pdk": pdk,
        "error": result.error_message,
        "log_path": str(result.log_path) if result.log_path else None,
    }


def run_eda_flow_sync_impl(
    *,
    backend: str,
    stage_start: str,
    design_name: str,
    design_config: str,
    pdk: str,
    stage_end: str | None = None,
    params: dict[str, Any] | None = None,
    clean: bool = False,
    create_flow_session_fn: Callable[..., int],
    save_run_and_parse_fn: Callable[..., int],
    record_decision_trace_fn: Callable[..., None],
    record_stage_outcome_fn: Callable[..., None],
    update_flow_session_status_fn: Callable[..., None],
) -> dict[str, Any]:
    """Run a sequence of EDA flow stages."""
    if clean:
        be = get_backend(backend)
        design = DesignSpec(
            name=design_name,
            config_path=Path(design_config),
            pdk=pdk,
        )
        subprocess.run(
            ["make", "clean", "-C", str(be._flow_dir), f"DESIGN_CONFIG={design.config_path}"],
            capture_output=True,
        )

    be = get_backend(backend)
    design = DesignSpec(
        name=design_name,
        config_path=Path(design_config),
        pdk=pdk,
    )

    supported_stages = be.get_supported_stages()

    if stage_start.lower() == "all":
        stages_to_run = supported_stages
    elif stage_end:
        try:
            start_idx = supported_stages.index(stage_start.lower())
            end_idx = supported_stages.index(stage_end.lower())
            if start_idx > end_idx:
                return {"error": f"Stage '{stage_start}' comes after '{stage_end}'"}
            stages_to_run = supported_stages[start_idx: end_idx + 1]
        except ValueError as e:
            return {"error": f"Invalid stage name: {e}"}
    else:
        if stage_start.lower() not in supported_stages:
            return {
                "error": f"Stage '{stage_start}' not supported. Valid: {supported_stages}"
            }
        stages_to_run = [stage_start.lower()]

    final_stage = stages_to_run[-1]
    session_id = create_flow_session_fn(
        design,
        objective=str((params or {}).get("_objective", "pnr")),
        notes=f"flow:{stage_start}->{stage_end or stage_start}",
    )

    results = []
    prev_run_id: int | None = None
    for stage_seq, stage in enumerate(stages_to_run, start=1):
        stage_result = be.run_stage(stage, design, params or {})

        source_run_id = prev_run_id
        run_db_id = save_run_and_parse_fn(
            stage_result,
            design,
            backend=be,
            run_context={
                "session_id": session_id,
                "stage_seq": stage_seq,
                "variant_tag": "baseline",
                "rerun_reason": f"flow:{stage_start}->{stage_end or stage_start}",
                "is_baseline": True,
                "is_selected": False,
                "parent_run_id": source_run_id,
            },
        )
        prev_run_id = run_db_id

        if source_run_id is not None:
            try:
                record_decision_trace_fn(
                    session_id=session_id,
                    source_run_id=source_run_id,
                    target_run_id=run_db_id,
                    llm_reason=f"session stage progression: {source_run_id}->{run_db_id}",
                    llm_reason_structured={
                        "kind": "session_stage_progression",
                        "source_run_id": source_run_id,
                        "target_run_id": run_db_id,
                        "stage": stage,
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to persist decision_trace %s->%s",
                    source_run_id,
                    run_db_id,
                )

        try:
            record_stage_outcome_fn(run_db_id, stage, stage_result)
        except Exception:
            logger.warning("Failed to persist stage_outcome for run %d", run_db_id)

        if stage_result.status.value == "success":
            try:
                from eda_agent.db.archiver import archive_run

                archive_run(run_db_id)
            except Exception:
                logger.warning("Parquet archival failed for run %d", run_db_id)

        results.append(
            {
                "stage": stage,
                "is_session_final_stage": stage == final_stage,
                "status": stage_result.status.value,
                "run_id": run_db_id,
                "run_uuid": stage_result.run_id,
                "error": stage_result.error_message,
                "log_path": str(stage_result.log_path) if stage_result.log_path else None,
            }
        )

        if stage_result.status.value != "success":
            try:
                update_flow_session_status_fn(session_id, status="failed")
            except Exception:
                logger.warning("Failed to mark flow_session %s failed", session_id)
            break

    all_success = all(r["status"] == "success" for r in results)
    overall_status = "success" if all_success else "partial_failure"

    try:
        if all_success and results and results[-1]["stage"] == final_stage:
            update_flow_session_status_fn(
                session_id,
                status="completed",
                baseline_run_id=results[-1]["run_id"],
            )
    except Exception:
        logger.warning("Failed to finalize flow_session %s", session_id)

    return {
        "overall_status": overall_status,
        "session_id": session_id,
        "session_final_stage": final_stage,
        "stages_run": len(results),
        "design_name": design_name,
        "pdk": pdk,
        "results": results,
    }
