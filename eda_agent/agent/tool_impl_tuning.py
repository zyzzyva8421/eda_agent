"""Implementation helpers for tuning and congestion optimization tools."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

import httpx

from eda_agent.backends.base import DesignSpec
from eda_agent.config import settings

logger = logging.getLogger(__name__)

# Ordered ORFS stages used for multi-stage traversal
ORFS_STAGE_ORDER: list[str] = ["synth", "floorplan", "place", "cts", "route", "finish"]


def check_ppa_target_impl(
    timing: dict[str, Any],
    target_spec: str,
    congestion_summary: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a natural-language PPA target against timing data."""
    summary = timing.get("summary", [])
    if not summary:
        return False

    latest = summary[0]
    spec_lower = target_spec.lower()

    metric_map = {
        "wns": "wns_ns",
        "tns": "tns_ns",
        "fmax": "fmax_mhz",
        "fep": "failing_endpoints",
        "failing_endpoints": "failing_endpoints",
        "failing endpoints": "failing_endpoints",
        "setup_violations": "setup_violations",
        "hold_violations": "hold_violations",
    }
    congestion_metric_map = {
        "overflow_h_pct": "overflow_h_pct",
        "overflow_v_pct": "overflow_v_pct",
    }

    timing_cond_re = re.compile(
        r"(wns|tns|fmax|fep|failing[_ ]endpoints|setup_violations|hold_violations)"
        r"\s*(>=|<=|>|<|==)\s*(-?[\d.]+)",
        re.IGNORECASE,
    )
    congestion_cond_re = re.compile(
        r"(overflow_h_pct|overflow_v_pct|overflow_pct|overflow)\s*(>=|<=|>|<|==)\s*(-?[\d.]+)%?",
        re.IGNORECASE,
    )

    timing_conditions = timing_cond_re.findall(spec_lower)
    congestion_conditions = congestion_cond_re.findall(spec_lower)
    if not timing_conditions and not congestion_conditions:
        return (latest.get("failing_endpoints") or 0) == 0

    def apply_op(op: str, actual: float, threshold: float) -> bool:
        if op == ">=":
            return actual >= threshold
        if op == "<=":
            return actual <= threshold
        if op == ">":
            return actual > threshold
        if op == "<":
            return actual < threshold
        if op == "==":
            return actual == threshold
        return False

    for metric_alias, op, raw_threshold in timing_conditions:
        data_key = metric_map.get(metric_alias.replace(" ", "_"))
        if data_key is None:
            continue
        actual = latest.get(data_key)
        if actual is None:
            return False
        if not apply_op(op, float(actual), float(raw_threshold)):
            return False

    if congestion_conditions:
        summary_data = congestion_summary or {}
        if not summary_data:
            return False
        for metric_alias, op, raw_threshold in congestion_conditions:
            alias = metric_alias.lower()
            if alias in {"overflow", "overflow_pct"}:
                overflow_h = float(summary_data.get("overflow_h_pct", 0.0) or 0.0)
                overflow_v = float(summary_data.get("overflow_v_pct", 0.0) or 0.0)
                actual = max(overflow_h, overflow_v)
            else:
                data_key = congestion_metric_map.get(alias)
                if data_key is None:
                    continue
                actual = summary_data.get(data_key)
            if actual is None:
                return False
            if not apply_op(op, float(actual), float(raw_threshold)):
                return False

    return True


def pick_bottleneck_stage_impl(
    timing: dict[str, Any],
    run_id: int | None = None,
    congestion_threshold_pct: float = 2.0,
    *,
    query_congestion_summary_fn: Callable[[int], dict[str, Any]],
) -> str:
    """Choose which stage to re-run based on violation profile."""
    summary = timing.get("summary", [{}])[0] if timing.get("summary") else {}
    if run_id is not None:
        try:
            congestion = query_congestion_summary_fn(run_id)
            overflow_h_pct = float(congestion.get("overflow_h_pct", 0.0) or 0.0)
            overflow_v_pct = float(congestion.get("overflow_v_pct", 0.0) or 0.0)
            if max(overflow_h_pct, overflow_v_pct) > congestion_threshold_pct:
                return "place"
        except Exception:
            logger.debug(
                "Failed to query congestion summary for run_id=%s",
                run_id,
                exc_info=True,
            )

    hold_vio = summary.get("hold_violations") or 0
    setup_vio = summary.get("setup_violations") or 0
    wns = summary.get("wns_ns") or 0.0
    fep = summary.get("failing_endpoints") or 0

    if hold_vio > 0:
        return "cts"
    if wns < -0.3 or setup_vio > 10 or fep > 20:
        return "cts"
    if fep > 0 or wns < 0:
        return "route"
    return "place"


def bbox_from_wkt_impl(geom_wkt: str) -> tuple[float, float, float, float] | None:
    points = re.findall(
        r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
        geom_wkt,
    )
    if len(points) < 4:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def heuristic_decide_blockages_impl(
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
    *,
    bbox_from_wkt_fn: Callable[[str], tuple[float, float, float, float] | None] = bbox_from_wkt_impl,
) -> list[dict[str, Any]]:
    selected = sorted(
        hotspots,
        key=lambda h: float(h.get("overflow", 0) or 0),
        reverse=True,
    )[:max_blockages]

    blockages: list[dict[str, Any]] = []
    for idx, hs in enumerate(selected, start=1):
        geom_wkt = hs.get("geom_wkt")
        bbox = bbox_from_wkt_fn(geom_wkt) if isinstance(geom_wkt, str) else None
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox
        blockages.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "type": "soft",
                "reason": (
                    f"heuristic_hotspot_rank_{idx}; "
                    f"overflow={hs.get('overflow', 0)}"
                ),
            }
        )
    return blockages


def llm_decide_blockages_impl(
    *,
    run_id: int,
    congestion_summary: dict[str, Any],
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
    heuristic_decide_blockages_fn: Callable[[list[dict[str, Any]], int], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Use LLM to decide blockage bounding boxes; fallback to heuristics."""
    if not hotspots:
        return []

    summary_json = json.dumps(congestion_summary, ensure_ascii=False)
    hotspot_sample = hotspots[:12]
    hotspot_json = json.dumps(hotspot_sample, ensure_ascii=False)

    system_prompt = (
        "You are an expert Innovus placement optimization engineer. "
        "Return ONLY JSON: {\"blockages\": [...]}\\n"
        "Each blockage item must include x1,y1,x2,y2,type,reason. "
        "Allowed type values: soft, hard, partial. "
        "Use no more than max_blockages items and prioritize highest overflow hotspots."
    )
    user_prompt = (
        f"run_id={run_id}\\n"
        f"max_blockages={max_blockages}\\n"
        f"congestion_summary={summary_json}\\n"
        f"hotspots={hotspot_json}\\n"
        "Output strict JSON only."
    )

    api_key = settings.minimax_api_key
    if not api_key:
        return heuristic_decide_blockages_fn(hotspots, max_blockages=max_blockages)

    model = settings.minimax_model
    base_url = settings.minimax_base_url.rstrip("/")
    group_id = settings.minimax_group_id
    url = (
        f"{base_url}/text/chatcompletion_v2?GroupId={group_id}"
        if group_id
        else f"{base_url}/chat/completions"
    )

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 800,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        raw_blockages = parsed.get("blockages", [])
        if not isinstance(raw_blockages, list):
            return heuristic_decide_blockages_fn(hotspots, max_blockages=max_blockages)
        validated: list[dict[str, Any]] = []
        for item in raw_blockages[:max_blockages]:
            if not isinstance(item, dict):
                continue
            try:
                x1 = float(item["x1"])
                y1 = float(item["y1"])
                x2 = float(item["x2"])
                y2 = float(item["y2"])
            except Exception:
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            btype = str(item.get("type", "soft")).lower()
            if btype not in {"soft", "hard", "partial"}:
                btype = "soft"
            validated.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "type": btype,
                    "reason": str(item.get("reason", "llm_hotspot")),
                }
            )
        if validated:
            return validated
    except Exception:
        logger.warning("LLM blockage decision failed; using heuristic fallback", exc_info=True)

    return heuristic_decide_blockages_fn(hotspots, max_blockages=max_blockages)


def tune_congestion_with_blockage_impl(
    backend: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    congestion_threshold_pct: float = 2.0,
    max_iterations: int = 5,
    workdir: str | None = None,
    *,
    resolve_backend_design_identity_fn: Callable[..., tuple[str, str]],
    run_eda_stage_fn: Callable[..., dict[str, Any]],
    query_congestion_summary_fn: Callable[[int], dict[str, Any]],
    query_congestion_fn: Callable[..., list[dict[str, Any]]],
    llm_decide_blockages_fn: Callable[..., list[dict[str, Any]]],
    add_placement_blockage_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Iteratively tune place congestion by adding placement blockages."""
    history: list[dict[str, Any]] = []

    design_config, pdk = resolve_backend_design_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    for iteration in range(1, max_iterations + 1):
        run_result = run_eda_stage_fn(
            backend=backend,
            stage="place",
            design_name=design_name,
            design_config=design_config,
            pdk=pdk,
            params={"workdir": workdir} if workdir else {},
        )
        run_id = run_result.get("run_id")
        status = run_result.get("status")
        iter_row: dict[str, Any] = {
            "iteration": iteration,
            "run_id": run_id,
            "status": status,
            "target_threshold_pct": congestion_threshold_pct,
        }
        if status != "success" or run_id is None:
            iter_row["error"] = run_result.get("error")
            history.append(iter_row)
            break

        summary = query_congestion_summary_fn(run_id)
        iter_row["congestion_summary"] = summary

        overflow_h_pct = float(summary.get("overflow_h_pct", 0.0) or 0.0)
        overflow_v_pct = float(summary.get("overflow_v_pct", 0.0) or 0.0)
        has_pct = ("overflow_h_pct" in summary) or ("overflow_v_pct" in summary)
        effective_overflow = (
            max(overflow_h_pct, overflow_v_pct)
            if has_pct
            else float(summary.get("total_overflow", 0.0) or 0.0)
        )
        iter_row["effective_overflow"] = effective_overflow
        iter_row["overflow_basis"] = "pct" if has_pct else "count"

        if effective_overflow <= congestion_threshold_pct:
            iter_row["converged"] = True
            history.append(iter_row)
            return {
                "converged": True,
                "iterations": iteration,
                "threshold_pct": congestion_threshold_pct,
                "history": history,
            }

        hotspots = query_congestion_fn(run_id)
        iter_row["hotspot_count"] = len(hotspots)
        if not hotspots:
            iter_row["converged"] = False
            iter_row["error"] = "No congestion hotspots found for blockage synthesis"
            history.append(iter_row)
            break

        blockages = llm_decide_blockages_fn(
            run_id=run_id,
            congestion_summary=summary,
            hotspots=hotspots,
        )
        if not blockages:
            iter_row["converged"] = False
            iter_row["error"] = "No valid blockage candidates produced"
            history.append(iter_row)
            break

        apply_result = add_placement_blockage_fn(
            run_id=run_id,
            blockages=blockages,
            workdir=workdir,
            stage="place",
        )
        iter_row["applied_blockages"] = blockages
        iter_row["blockage_apply_result"] = apply_result
        history.append(iter_row)

    return {
        "converged": False,
        "iterations": len(history),
        "threshold_pct": congestion_threshold_pct,
        "history": history,
    }


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
