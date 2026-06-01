"""Implementation helpers for parameter suggestion and filtering tools."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import text

from eda_agent.agent.param_mapper import PARAM_MAPPER, OptimizationObjective
from eda_agent.config import settings
from eda_agent.db.session import get_db
from eda_agent.tracing import is_tracing_enabled, trace_chat

logger = logging.getLogger(__name__)


def infer_objective_from_target_spec_impl(
    target_spec: str,
    timing_summary: dict[str, Any] | None = None,
) -> OptimizationObjective:
    """Infer the primary optimization objective from natural-language target text."""
    spec = target_spec.lower()
    if any(token in spec for token in ("leakage", "leak", "static power")):
        return OptimizationObjective.LEAKAGE
    if any(token in spec for token in ("dynamic", "switching power")):
        return OptimizationObjective.DYNAMIC
    if any(token in spec for token in ("area", "utilization", "utilisation", "density")):
        return OptimizationObjective.AREA
    if any(token in spec for token in ("congestion", "overflow", "hotspot", "route overflow")):
        return OptimizationObjective.CONGESTION
    if any(token in spec for token in ("power", "total power")):
        return OptimizationObjective.DYNAMIC

    summary = timing_summary or {}
    if (summary.get("hold_violations") or 0) > 0:
        return OptimizationObjective.SETUP
    return OptimizationObjective.SETUP


def coerce_innovus_param_value_impl(raw_value: Any, sample_values: list[Any]) -> Any:
    """Coerce LLM/heuristic output into the sample domain expected by PARAM_MAPPER."""
    if isinstance(raw_value, str):
        lowered = raw_value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False

        has_numeric_sample = any(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            for v in sample_values
        )
        if has_numeric_sample:
            try:
                numeric = float(raw_value)
                if any(
                    isinstance(v, int) and not isinstance(v, bool)
                    for v in sample_values
                ) and numeric.is_integer():
                    return int(numeric)
                return numeric
            except ValueError:
                return raw_value

    return raw_value


def filter_suggested_params_impl(
    raw_params: dict[str, Any],
    backend: str,
    stage: str,
) -> dict[str, Any]:
    """Filter suggestions into backend-safe parameter values."""
    if backend.lower() != "innovus":
        filtered: dict[str, Any] = {}
        for key, value in raw_params.items():
            if isinstance(value, (int, float)):
                filtered[key] = value
                continue
            if isinstance(value, str):
                try:
                    float(value)
                    filtered[key] = value
                except ValueError:
                    logger.debug(
                        "Dropping non-numeric suggestion for backend %s: %s=%r",
                        backend,
                        key,
                        value,
                    )
        return filtered

    stage_specs = PARAM_MAPPER.get_flow_stage_params(stage)
    filtered = {}
    for key, value in raw_params.items():
        spec = stage_specs.get(key)
        if spec is None:
            logger.debug("Dropping unknown Innovus param suggestion %s=%r", key, value)
            continue

        coerced = coerce_innovus_param_value_impl(value, spec.sample_values)
        if coerced in spec.sample_values:
            filtered[key] = coerced
            continue

        logger.debug(
            "Dropping out-of-domain Innovus param suggestion %s=%r; allowed=%s",
            key,
            value,
            spec.sample_values,
        )

    return filtered


def llm_suggest_params_impl(
    run_id: int,
    target_spec: str,
    ts_row: dict,
    run_row: dict,
    us_row: dict,
    history: list[dict],
    worst_paths: list[dict] | None = None,
) -> dict[str, Any]:
    """Call the MiniMax LLM to produce parameter suggestions."""
    context_parts = [
        f"Design: {run_row.get('design_name', 'unknown')}  PDK: {run_row.get('pdk', 'unknown')}",
        f"Backend: {run_row.get('backend', 'unknown')}",
        f"Stage: {run_row.get('stage', 'unknown')}",
        f"Current params: {json.dumps(run_row.get('params') or {})}",
        "",
        "## Current run metrics",
    ]
    if str(run_row.get("backend", "")).lower() == "innovus":
        stage_catalog = PARAM_MAPPER.build_stage_catalog().get(run_row.get("stage", ""), [])
        if stage_catalog:
            context_parts.append("")
            context_parts.append("## Allowed Innovus tunable parameters for this stage")
            for item in stage_catalog:
                context_parts.append(
                    f"  {item['name']}: values={item['sample_values']} command={item['tcl_command']}"
                )
    if ts_row:
        context_parts.append(
            f"  Timing – WNS: {ts_row.get('wns_ns')} ns, "
            f"TNS: {ts_row.get('tns_ns')} ns, "
            f"Failing endpoints: {ts_row.get('failing_endpoints')}"
        )
        extras = []
        if ts_row.get("fmax_mhz") is not None:
            extras.append(f"Fmax: {ts_row['fmax_mhz']} MHz")
        if ts_row.get("clock_skew_ns") is not None:
            extras.append(f"Clock skew: {ts_row['clock_skew_ns']} ns")
        if ts_row.get("setup_violations") is not None:
            extras.append(f"Setup violations: {ts_row['setup_violations']}")
        if ts_row.get("hold_violations") is not None:
            extras.append(f"Hold violations: {ts_row['hold_violations']}")
        if ts_row.get("max_slew_violations") is not None:
            extras.append(f"Slew violations: {ts_row['max_slew_violations']}")
        if ts_row.get("max_fanout_violations") is not None:
            extras.append(f"Fanout violations: {ts_row['max_fanout_violations']}")
        if ts_row.get("max_cap_violations") is not None:
            extras.append(f"Cap violations: {ts_row['max_cap_violations']}")
        if ts_row.get("critical_path_delay_ns") is not None:
            extras.append(f"Critical path delay: {ts_row['critical_path_delay_ns']} ns")
        if extras:
            context_parts.append("  Extended – " + ", ".join(extras))
    if us_row:
        context_parts.append(
            f"  Utilization – Area: {us_row.get('design_area_um2')} µm², "
            f"Util%: {us_row.get('utilization_pct')}, "
            f"Cells: {us_row.get('num_cells')}"
        )
    if worst_paths:
        context_parts.append("")
        context_parts.append("## Worst timing paths (most negative slack first)")
        for p in worst_paths:
            context_parts.append(
                f"  slack={p.get('slack_ns')} ns  group={p.get('path_group')}  "
                f"{p.get('startpoint', '')} → {p.get('endpoint', '')}"
            )
    if history:
        context_parts.append("")
        context_parts.append("## Recent run history (newest first)")
        for h in history:
            context_parts.append(
                f"  run_id={h.get('id')} stage={h.get('stage')} "
                f"WNS={h.get('wns_ns')} TNS={h.get('tns_ns')} "
                f"FEP={h.get('failing_endpoints')} params={h.get('params')}"
            )

    if str(run_row.get("backend", "")).lower() == "innovus":
        system_prompt = (
            "You are an expert Cadence Innovus physical design engineer. "
            "Given current metrics and run history, output ONLY a JSON object with two keys:\n"
            '  "suggested_params": an object mapping parameter names to values chosen ONLY from the '
            "allowed Innovus stage catalog shown in the prompt. Values may be booleans, enums, or numeric values. "
            "NEVER use relative adjustments like 'increase by X' or values outside the listed sample set.\n"
            '  "reasoning": an array of concise strings explaining each suggestion.\n'
            "Do NOT include any other text outside the JSON object."
        )
    else:
        system_prompt = (
            "You are an expert EDA physical design engineer specialised in VLSI PPA optimisation "
            "with OpenROAD Flow Scripts (ORFS). "
            "Given current metrics and run history, output ONLY a JSON object with two keys:\n"
            '  "suggested_params": an object mapping ORFS make variable names to CONCRETE NUMERIC '
            "values (integers or floats). "
            "NEVER use relative adjustments like 'increase by X' or 'reduce by Y%'. "
            "Always compute the absolute target value from the current params shown above.\n"
            '  "reasoning": an array of concise strings explaining each suggestion.\n'
            "Do NOT include any other text outside the JSON object."
        )
    user_msg = (
        f"PPA target: {target_spec}\n\n"
        + "\n".join(context_parts)
        + "\n\nSuggest ORFS parameter changes to reach the PPA target. "
        "Return concrete numeric values only."
    )

    api_key = settings.minimax_api_key
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
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 1024,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60, proxy=None) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        raw_response = resp.json()

    if is_tracing_enabled():
        raw_response = trace_chat(
            messages=payload["messages"],
            response=raw_response,
            model=model,
        )

    content = raw_response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.rsplit("```", 1)[0].strip()

    parsed = json.loads(content)
    return {
        "suggested_params": parsed.get("suggested_params", {}),
        "reasoning": parsed.get("reasoning", []),
    }


def suggest_params_impl(
    run_id: int,
    target_spec: str,
    *,
    llm_suggest_params_fn=llm_suggest_params_impl,
) -> dict[str, Any]:
    """LLM-backed parameter suggestions with heuristic fallback."""
    with get_db() as db:
        ts_row = db.execute(
            text(
                "SELECT wns_ns, tns_ns, failing_endpoints, "
                "       fmax_mhz, clock_skew_ns, max_slew_violations, "
                "       max_fanout_violations, max_cap_violations, "
                "       setup_violations, hold_violations, "
                "       critical_path_delay_ns, slack_cpd_ratio_pct "
                "FROM timing_summary WHERE run_id = :rid "
                "ORDER BY wns_ns ASC LIMIT 1"
            ),
            {"rid": run_id},
        ).mappings().first()

        run_row = db.execute(
            text(
                "SELECT r.params, r.stage, d.name AS design_name, d.pdk, b.name AS backend "
                "FROM runs r "
                "JOIN designs d ON d.id = r.design_id "
                "JOIN backends b ON b.id = r.backend_id "
                "WHERE r.id = :rid"
            ),
            {"rid": run_id},
        ).mappings().first()

        us_row = db.execute(
            text(
                "SELECT design_area_um2, utilization_pct, num_cells "
                "FROM utilization_summary WHERE run_id = :rid LIMIT 1"
            ),
            {"rid": run_id},
        ).mappings().first()

        path_rows = db.execute(
            text(
                "SELECT startpoint, endpoint, path_group, slack_ns "
                "FROM timing_paths WHERE run_id = :rid "
                "ORDER BY slack_ns ASC LIMIT 5"
            ),
            {"rid": run_id},
        ).mappings().fetchall()

        design_name = run_row["design_name"] if run_row else ""
        history_rows = db.execute(
            text(
                """
                SELECT r.id, r.stage, r.params, r.status,
                       ts.wns_ns, ts.tns_ns, ts.failing_endpoints
                FROM runs r
                JOIN designs d ON d.id = r.design_id
                LEFT JOIN timing_summary ts ON ts.run_id = r.id
                WHERE d.name = :dname AND r.id != :rid
                ORDER BY r.created_at DESC
                LIMIT 5
                """
            ),
            {"dname": design_name, "rid": run_id},
        ).mappings().fetchall()

    try:
        suggestions = llm_suggest_params_fn(
            run_id=run_id,
            target_spec=target_spec,
            ts_row=dict(ts_row) if ts_row else {},
            run_row=dict(run_row) if run_row else {},
            us_row=dict(us_row) if us_row else {},
            history=[dict(r) for r in history_rows],
            worst_paths=[dict(p) for p in path_rows],
        )
        return {
            **suggestions,
            "run_id": run_id,
            "target_spec": target_spec,
            "source": "llm",
        }
    except Exception:
        logger.warning("LLM suggest_params failed; falling back to heuristics", exc_info=True)

    suggestions_h: dict[str, Any] = {}
    reasoning: list[str] = []
    backend_name = (run_row.get("backend") if run_row else "") or ""
    stage_name = (run_row.get("stage") if run_row else "") or ""

    if backend_name.lower() == "innovus":
        objective = infer_objective_from_target_spec_impl(
            target_spec,
            dict(ts_row) if ts_row else {},
        )
        available_specs = PARAM_MAPPER.get_flow_stage_params(stage_name)
        suggested = PARAM_MAPPER.suggest_params(objective)
        suggestions_h = {
            key: value for key, value in suggested.items() if key in available_specs
        }

        reasoning.append(
            f"Using Innovus stage catalog for stage '{stage_name}' with objective '{objective.value}'."
        )
        if ts_row:
            wns = ts_row.get("wns_ns")
            hold_vio = ts_row.get("hold_violations")
            fep = ts_row.get("failing_endpoints")
            if wns is not None:
                reasoning.append(
                    f"Current WNS={wns:.3f}ns drives stage-specific tuning selection."
                )
            if hold_vio:
                reasoning.append(
                    f"Detected hold violations={hold_vio}; CTS/post-CTS skew knobs are prioritised."
                )
            if fep:
                reasoning.append(
                    f"Detected failing endpoints={fep}; timing and congestion knobs are prioritised."
                )

        return {
            "run_id": run_id,
            "target_spec": target_spec,
            "suggested_params": suggestions_h,
            "reasoning": reasoning,
            "available_params": sorted(available_specs.keys()),
            "stage_catalog": PARAM_MAPPER.build_stage_catalog().get(stage_name, []),
            "source": "heuristic",
        }

    if ts_row:
        wns = ts_row["wns_ns"] or 0.0
        fep = ts_row["failing_endpoints"] or 0
        hold_vio = ts_row.get("hold_violations") or 0
        slew_vio = ts_row.get("max_slew_violations") or 0

        current_params: dict[str, Any] = {}
        if run_row and run_row.get("params"):
            params = run_row["params"]
            current_params = params if isinstance(params, dict) else {}

        current_period = None
        try:
            current_period = float(current_params.get("CLOCK_PERIOD", ""))
        except (TypeError, ValueError):
            pass

        if wns < -0.5:
            if current_period is not None:
                new_period = round(current_period + 0.5, 3)
                suggestions_h["CLOCK_PERIOD"] = new_period
                reasoning.append(
                    f"WNS={wns:.3f}ns is highly negative; relaxing CLOCK_PERIOD "
                    f"from {current_period} to {new_period} ns."
                )
            else:
                reasoning.append(
                    "WNS is highly negative; consider relaxing "
                    f"CLOCK_PERIOD by ~0.5 ns (current WNS={wns:.3f} ns)."
                )
        elif wns < -0.1:
            suggestions_h["TNS_END_PERCENT"] = 20
            reasoning.append(
                f"WNS={wns:.3f}ns; tightening TNS endpoint coverage to 20%."
            )

        if fep > 10:
            current_util = None
            try:
                current_util = float(current_params.get("CORE_UTILIZATION", ""))
            except (TypeError, ValueError):
                pass
            if current_util is not None:
                new_util = max(10, round(current_util - 5, 1))
                suggestions_h["CORE_UTILIZATION"] = new_util
                reasoning.append(
                    f"High FEP ({fep}); reducing CORE_UTILIZATION "
                    f"from {current_util} to {new_util}%."
                )
            else:
                reasoning.append(
                    f"High FEP ({fep}); consider reducing CORE_UTILIZATION by ~5%."
                )

        if hold_vio > 0:
            reasoning.append(
                f"Hold violations detected ({hold_vio}); consider increasing "
                "CTS_BUF_CELL hold margin or enabling hold-fixing in CTS."
            )

        if slew_vio > 5:
            reasoning.append(
                f"High slew violations ({slew_vio}); consider increasing "
                "MAX_SLEW_REPORTING_THRESHOLD or adjusting driver sizing."
            )

    return {
        "run_id": run_id,
        "target_spec": target_spec,
        "suggested_params": suggestions_h,
        "reasoning": reasoning,
        "source": "heuristic",
    }
