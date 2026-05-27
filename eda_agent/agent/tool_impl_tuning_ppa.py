"""PPA tuning loops (single-stage and multi-stage)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from eda_agent.backends.base import DesignSpec

logger = logging.getLogger(__name__)

ORFS_STAGE_ORDER: list[str] = ["synth", "floorplan", "place", "cts", "route", "finish"]


def tune_ppa_impl(
    backend: str,
    stage: str,
    design_name: str,
    target_spec: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    max_iterations: int = 5,
    *,
    resolve_backend_design_identity_fn: Callable[..., tuple[str, str]],
    create_flow_session_fn: Callable[..., int],
    run_eda_stage_fn: Callable[..., dict[str, Any]],
    update_flow_session_status_fn: Callable[..., None],
    record_decision_trace_fn: Callable[..., None],
    query_timing_fn: Callable[..., dict[str, Any]],
    query_congestion_summary_fn: Callable[[int], dict[str, Any]],
    check_ppa_target_fn: Callable[..., bool],
    suggest_params_fn: Callable[[int, str], dict[str, Any]],
    filter_suggested_params_fn: Callable[[dict[str, Any], str, str], dict[str, Any]],
    latest_inference_context_for_run_fn: Callable[[int], dict[str, Any]],
    decision_reason_from_suggestion_fn: Callable[[dict[str, Any], str], str],
    decision_reason_structured_from_suggestion_fn: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """Autonomous PPA tuning loop with hill-climbing direction memory."""
    history: list[dict[str, Any]] = []
    current_params: dict[str, Any] = {}
    best_wns: float | None = None

    design_config, pdk = resolve_backend_design_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    design = DesignSpec(name=design_name, config_path=Path(design_config), pdk=pdk)
    session_id = create_flow_session_fn(
        design,
        objective="tune_ppa",
        notes=f"tune_ppa:{stage}:{target_spec}",
    )

    prev_run_id: int | None = None
    pending_decision: dict[str, Any] | None = None
    session_stage_seq = 0
    target_reached = False
    session_failed = False

    for iteration in range(1, max_iterations + 1):
        logger.info(
            "tune_ppa iteration %d/%d params=%s",
            iteration,
            max_iterations,
            current_params,
        )

        session_stage_seq += 1
        rerun_reason = (
            str(pending_decision.get("reason", ""))
            if pending_decision
            else f"tune_ppa iteration {iteration}"
        )
        pending_inference_id = (
            pending_decision.get("inference_id") if pending_decision else None
        )

        run_result = run_eda_stage_fn(
            backend=backend,
            stage=stage,
            design_name=design_name,
            design_config=design_config,
            pdk=pdk,
            params=current_params,
            run_context={
                "session_id": session_id,
                "stage_seq": session_stage_seq,
                "variant_tag": f"iter_{iteration}",
                "rerun_reason": rerun_reason,
                "is_baseline": iteration == 1,
                "is_selected": False,
                "parent_run_id": prev_run_id,
                "root_cause_inference_id": pending_inference_id,
            },
        )

        run_db_id = run_result.get("run_id")
        status = run_result.get("status")

        iteration_record: dict[str, Any] = {
            "iteration": iteration,
            "params": current_params,
            "run_id": run_db_id,
            "status": status,
            "target_met": False,
            "improved": False,
        }

        if status != "success" or run_db_id is None:
            iteration_record["error"] = run_result.get("error")
            history.append(iteration_record)
            session_failed = True
            try:
                update_flow_session_status_fn(session_id, status="failed")
            except Exception:
                logger.warning("Failed to mark tune_ppa flow_session %s failed", session_id)
            break

        if pending_decision is not None:
            try:
                record_decision_trace_fn(
                    session_id=session_id,
                    source_run_id=int(pending_decision["source_run_id"]),
                    target_run_id=run_db_id,
                    llm_reason=str(pending_decision.get("reason", "")),
                    llm_reason_structured=pending_decision.get("reason_structured"),
                    inference_id=pending_decision.get("inference_id"),
                    case_id=pending_decision.get("case_id"),
                    rule_id=pending_decision.get("rule_id"),
                )
            except Exception:
                logger.warning(
                    "Failed to persist decision_trace %s->%s",
                    pending_decision.get("source_run_id"),
                    run_db_id,
                )
            finally:
                pending_decision = None

        prev_run_id = run_db_id

        timing = query_timing_fn(design_name, stage=stage, run_id=run_db_id, limit=1)
        summary = timing.get("summary", [])
        current_wns: float | None = None
        if summary:
            current_wns = summary[0].get("wns_ns")
            iteration_record["wns_ns"] = current_wns
            iteration_record["tns_ns"] = summary[0].get("tns_ns")
            iteration_record["failing_endpoints"] = summary[0].get("failing_endpoints")

        if current_wns is not None:
            if best_wns is None or current_wns > best_wns:
                best_wns = current_wns
                iteration_record["improved"] = True
            else:
                iteration_record["improved"] = False

        congestion_summary = query_congestion_summary_fn(run_db_id)
        target_met = check_ppa_target_fn(
            timing,
            target_spec,
            congestion_summary=congestion_summary,
        )
        iteration_record["target_met"] = target_met
        iteration_record["congestion_summary"] = congestion_summary
        history.append(iteration_record)

        if target_met:
            logger.info("tune_ppa: target met at iteration %d", iteration)
            target_reached = True
            try:
                update_flow_session_status_fn(
                    session_id,
                    status="completed",
                    baseline_run_id=run_db_id,
                )
            except Exception:
                logger.warning("Failed to finalize tune_ppa flow_session %s", session_id)
            break

        if iteration < max_iterations:
            augmented_spec = target_spec
            if not iteration_record["improved"] and iteration > 1:
                augmented_spec = (
                    f"{target_spec} "
                    f"[last params did NOT improve WNS; try a different direction]"
                )

            suggestion = suggest_params_fn(run_db_id, augmented_spec)
            raw_params = suggestion.get("suggested_params", {})

            filtered = filter_suggested_params_fn(raw_params, backend=backend, stage=stage)

            if not filtered and raw_params:
                logger.warning(
                    "tune_ppa: all suggested params were dropped after validation; "
                    "re-running with same params (iteration %d)",
                    iteration,
                )
            current_params = filtered
            infer_ctx = latest_inference_context_for_run_fn(run_db_id)
            reason_prefix = f"tune_ppa iteration {iteration} -> {iteration + 1}"
            pending_decision = {
                "source_run_id": run_db_id,
                "reason": decision_reason_from_suggestion_fn(
                    suggestion,
                    prefix=reason_prefix,
                ),
                "reason_structured": decision_reason_structured_from_suggestion_fn(
                    suggestion,
                    prefix=reason_prefix,
                ),
                "inference_id": infer_ctx.get("inference_id"),
                "case_id": infer_ctx.get("case_id"),
                "rule_id": infer_ctx.get("rule_id"),
            }

    if not target_reached and not session_failed:
        try:
            update_flow_session_status_fn(session_id, status="failed")
        except Exception:
            logger.warning("Failed to close tune_ppa flow_session %s", session_id)

    return {
        "session_id": session_id,
        "iterations_run": len(history),
        "target_spec": target_spec,
        "target_met": any(r.get("target_met") for r in history),
        "best_wns_ns": best_wns,
        "history": history,
    }


def tune_ppa_multistage_impl(
    backend: str,
    design_name: str,
    target_spec: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    start_stage: str = "place",
    max_iterations: int = 5,
    *,
    resolve_backend_design_identity_fn: Callable[..., tuple[str, str]],
    create_flow_session_fn: Callable[..., int],
    run_eda_stage_fn: Callable[..., dict[str, Any]],
    update_flow_session_status_fn: Callable[..., None],
    record_decision_trace_fn: Callable[..., None],
    query_timing_fn: Callable[..., dict[str, Any]],
    query_congestion_summary_fn: Callable[[int], dict[str, Any]],
    check_ppa_target_fn: Callable[..., bool],
    pick_bottleneck_stage_fn: Callable[..., str],
    suggest_params_fn: Callable[[int, str], dict[str, Any]],
    filter_suggested_params_fn: Callable[[dict[str, Any], str, str], dict[str, Any]],
    latest_inference_context_for_run_fn: Callable[[int], dict[str, Any]],
    decision_reason_from_suggestion_fn: Callable[[dict[str, Any], str], str],
    decision_reason_structured_from_suggestion_fn: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """Multi-stage autonomous PPA tuning loop with lineage persistence."""
    history: list[dict[str, Any]] = []
    stage_params: dict[str, dict[str, Any]] = {}
    rerun_from: str = start_stage
    best_wns: float | None = None

    design_config, pdk = resolve_backend_design_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    design = DesignSpec(name=design_name, config_path=Path(design_config), pdk=pdk)
    session_id = create_flow_session_fn(
        design,
        objective="tune_ppa_multistage",
        notes=f"tune_ppa_multistage:{start_stage}:{target_spec}",
    )

    prev_run_id: int | None = None
    pending_decision: dict[str, Any] | None = None
    session_stage_seq = 0
    target_reached = False
    session_failed = False

    try:
        start_idx = ORFS_STAGE_ORDER.index(start_stage)
    except ValueError:
        start_idx = 0

    for iteration in range(1, max_iterations + 1):
        logger.info(
            "tune_ppa_multistage iteration %d/%d  rerun_from=%s  stage_params=%s",
            iteration,
            max_iterations,
            rerun_from,
            stage_params,
        )

        try:
            rerun_idx = ORFS_STAGE_ORDER.index(rerun_from)
        except ValueError:
            rerun_idx = start_idx

        stages_to_run = ORFS_STAGE_ORDER[rerun_idx:]

        iteration_record: dict[str, Any] = {
            "iteration": iteration,
            "rerun_from": rerun_from,
            "stages_run": [],
            "target_met": False,
            "improved": False,
        }

        last_run_id: int | None = None
        last_timing: dict[str, Any] = {}
        decision_consumed = False

        for stage in stages_to_run:
            params = stage_params.get(stage, {})
            session_stage_seq += 1
            rerun_reason = (
                str(pending_decision.get("reason", ""))
                if pending_decision and not decision_consumed
                else f"tune_ppa_multistage iter={iteration} stage={stage}"
            )
            pending_inference_id = (
                pending_decision.get("inference_id")
                if pending_decision and not decision_consumed
                else None
            )
            run_result = run_eda_stage_fn(
                backend=backend,
                stage=stage,
                design_name=design_name,
                design_config=design_config,
                pdk=pdk,
                params=params,
                run_context={
                    "session_id": session_id,
                    "stage_seq": session_stage_seq,
                    "variant_tag": f"iter_{iteration}",
                    "rerun_reason": rerun_reason,
                    "is_baseline": iteration == 1,
                    "is_selected": False,
                    "parent_run_id": prev_run_id,
                    "root_cause_inference_id": pending_inference_id,
                },
            )
            stage_record: dict[str, Any] = {
                "stage": stage,
                "run_id": run_result.get("run_id"),
                "status": run_result.get("status"),
                "params": params,
            }
            if run_result.get("status") != "success":
                stage_record["error"] = run_result.get("error")
                iteration_record["stages_run"].append(stage_record)
                session_failed = True
                try:
                    update_flow_session_status_fn(session_id, status="failed")
                except Exception:
                    logger.warning(
                        "Failed to mark tune_ppa_multistage flow_session %s failed",
                        session_id,
                    )
                break

            last_run_id = run_result.get("run_id")
            if isinstance(last_run_id, int):
                if pending_decision is not None and not decision_consumed:
                    try:
                        record_decision_trace_fn(
                            session_id=session_id,
                            source_run_id=int(pending_decision["source_run_id"]),
                            target_run_id=last_run_id,
                            llm_reason=str(pending_decision.get("reason", "")),
                            llm_reason_structured=pending_decision.get("reason_structured"),
                            inference_id=pending_decision.get("inference_id"),
                            case_id=pending_decision.get("case_id"),
                            rule_id=pending_decision.get("rule_id"),
                        )
                    except Exception:
                        logger.warning(
                            "Failed to persist decision_trace %s->%s",
                            pending_decision.get("source_run_id"),
                            last_run_id,
                        )
                    decision_consumed = True
                    pending_decision = None

                prev_run_id = last_run_id

            timing = query_timing_fn(design_name, stage=stage, run_id=last_run_id, limit=1)
            ts = timing.get("summary", [{}])[0] if timing.get("summary") else {}
            stage_record["wns_ns"] = ts.get("wns_ns")
            stage_record["tns_ns"] = ts.get("tns_ns")
            stage_record["failing_endpoints"] = ts.get("failing_endpoints")
            iteration_record["stages_run"].append(stage_record)

            if stage == "finish":
                last_timing = timing

        if not iteration_record["stages_run"]:
            history.append(iteration_record)
            break

        if not last_timing and last_run_id:
            last_timing = query_timing_fn(design_name, run_id=last_run_id, limit=1)

        fin_summary = last_timing.get("summary", [{}])[0] if last_timing.get("summary") else {}
        current_wns = fin_summary.get("wns_ns")
        if current_wns is not None:
            iteration_record["wns_ns"] = current_wns
            if best_wns is None or current_wns > best_wns:
                best_wns = current_wns
                iteration_record["improved"] = True

        final_congestion_summary = query_congestion_summary_fn(last_run_id) if last_run_id else {}
        target_met = check_ppa_target_fn(
            last_timing,
            target_spec,
            congestion_summary=final_congestion_summary,
        )
        iteration_record["target_met"] = target_met
        iteration_record["congestion_summary"] = final_congestion_summary
        history.append(iteration_record)

        if target_met:
            logger.info("tune_ppa_multistage: target met at iteration %d", iteration)
            target_reached = True
            try:
                update_flow_session_status_fn(
                    session_id,
                    status="completed",
                    baseline_run_id=last_run_id,
                )
            except Exception:
                logger.warning(
                    "Failed to finalize tune_ppa_multistage flow_session %s",
                    session_id,
                )
            break

        if iteration < max_iterations and last_run_id is not None:
            bottleneck = pick_bottleneck_stage_fn(last_timing, run_id=last_run_id)

            augmented_spec = target_spec
            if not iteration_record["improved"] and iteration > 1:
                augmented_spec = (
                    f"{target_spec} "
                    f"[last params did NOT improve WNS; try a different direction]"
                )

            suggestion = suggest_params_fn(last_run_id, augmented_spec)
            raw_params = suggestion.get("suggested_params", {})

            filtered = filter_suggested_params_fn(raw_params, backend=backend, stage=bottleneck)

            if filtered:
                stage_params[bottleneck] = filtered
                rerun_from = bottleneck
                iteration_record["next_bottleneck_stage"] = bottleneck
                iteration_record["next_params"] = filtered
            else:
                rerun_from = bottleneck

            infer_ctx = latest_inference_context_for_run_fn(last_run_id)
            reason_prefix = (
                f"tune_ppa_multistage iteration {iteration} "
                f"rerun_from={rerun_from}"
            )
            pending_decision = {
                "source_run_id": last_run_id,
                "reason": decision_reason_from_suggestion_fn(
                    suggestion,
                    prefix=reason_prefix,
                ),
                "reason_structured": decision_reason_structured_from_suggestion_fn(
                    suggestion,
                    prefix=reason_prefix,
                ),
                "inference_id": infer_ctx.get("inference_id"),
                "case_id": infer_ctx.get("case_id"),
                "rule_id": infer_ctx.get("rule_id"),
            }

    if not target_reached and not session_failed:
        try:
            update_flow_session_status_fn(session_id, status="failed")
        except Exception:
            logger.warning("Failed to close tune_ppa_multistage flow_session %s", session_id)

    return {
        "session_id": session_id,
        "iterations_run": len(history),
        "target_spec": target_spec,
        "target_met": any(r.get("target_met") for r in history),
        "best_wns_ns": best_wns,
        "history": history,
    }
