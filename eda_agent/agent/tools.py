"""Agent tool definitions and implementations.

Each tool is exposed to the LLM as an OpenAI-style function-call tool.
The ``TOOL_SCHEMAS`` list contains the JSON schema for every tool.
The ``execute_tool`` dispatcher routes a function-call name → implementation.

Tools
-----
run_eda_stage       – invoke a backend stage
query_timing        – query timing metrics from the DB
query_congestion    – spatial congestion query via PostGIS
query_utilization   – query cell area / utilization metrics from the DB
query_power         – query power breakdown metrics from the DB
compare_runs        – diff PPA between two runs
suggest_params      – LLM-assisted parameter suggestion based on history
tune_ppa            – autonomous PPA tuning loop (suggest → run → repeat)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec
from eda_agent.config import settings
from eda_agent.db.session import get_db
from eda_agent.parsers import get_parser

logger = logging.getLogger(__name__)

# ── JSON schemas (OpenAI function-call format) ────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_eda_stage",
            "description": (
                "Run a single EDA flow stage (e.g. synth, place, route) for a "
                "given design and return the run_id and status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name: 'orfs', 'innovus', 'icc2', or custom.",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage to run (e.g. 'route').",
                    },
                    "design_name": {
                        "type": "string",
                        "description": "Top-level design/module name (e.g. 'gcd').",
                    },
                    "design_config": {
                        "type": "string",
                        "description": "Absolute path to the design config file.",
                    },
                    "pdk": {
                        "type": "string",
                        "description": "PDK identifier (e.g. 'sky130hd').",
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value EDA parameters (e.g. CORE_UTILIZATION).",
                    },
                },
                "required": ["backend", "stage", "design_name", "design_config", "pdk"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_timing",
            "description": (
                "Query timing results (WNS, TNS, failing endpoints) and worst slack paths "
                "from the database for a specific design, stage, and optional run_id. "
                "Returns both summary metrics and individual violating paths."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {"type": "string"},
                    "stage": {"type": "string", "description": "Filter by stage (optional)."},
                    "run_id": {"type": "integer", "description": "Specific run ID (optional)."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 10)."},
                },
                "required": ["design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_congestion",
            "description": (
                "Spatial congestion query. Returns hotspot polygons that overlap "
                "a bounding box (x1,y1,x2,y2) in chip coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "x1": {"type": "number"},
                    "y1": {"type": "number"},
                    "x2": {"type": "number"},
                    "y2": {"type": "number"},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_runs",
            "description": "Compare PPA metrics between two run IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id_a": {"type": "integer", "description": "Baseline run ID."},
                    "run_id_b": {"type": "integer", "description": "New run ID."},
                },
                "required": ["run_id_a", "run_id_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_params",
            "description": (
                "Based on the current run results and historical data, suggest "
                "parameter adjustments to improve PPA.  Returns a JSON object "
                "with recommended parameter key-value pairs and reasoning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "Current run ID to analyse."},
                    "target_spec": {
                        "type": "string",
                        "description": "Natural language PPA target, e.g. 'WNS >= -0.1ns'.",
                    },
                },
                "required": ["run_id", "target_spec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tune_ppa",
            "description": (
                "Autonomous PPA tuning loop: repeatedly suggests parameters, runs the EDA "
                "stage, and checks if the target is met.  Returns the iteration history "
                "and final PPA metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name (e.g. 'orfs').",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage to tune (e.g. 'route').",
                    },
                    "design_name": {"type": "string"},
                    "design_config": {
                        "type": "string",
                        "description": "Absolute path to design config.",
                    },
                    "pdk": {"type": "string"},
                    "target_spec": {
                        "type": "string",
                        "description": "Natural language PPA target, e.g. 'WNS >= -0.1ns'.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum tuning iterations (default 5).",
                    },
                },
                "required": [
                    "backend", "stage", "design_name", "design_config", "pdk", "target_spec",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_utilization",
            "description": (
                "Query design-area and cell-utilisation results from the database "
                "for a specific design, stage, and optional run_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {"type": "string"},
                    "stage": {"type": "string", "description": "Filter by stage (optional)."},
                    "run_id": {"type": "integer", "description": "Specific run ID (optional)."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 10)."},
                },
                "required": ["design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_power",
            "description": (
                "Query power breakdown (internal / switching / leakage / total) in Watts "
                "from the database for a specific design, stage, and optional run_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {"type": "string"},
                    "stage": {"type": "string", "description": "Filter by stage (optional)."},
                    "run_id": {"type": "integer", "description": "Specific run ID (optional)."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 10)."},
                },
                "required": ["design_name"],
            },
        },
    },
]


# ── Tool implementations ──────────────────────────────────────────────────────


def _run_eda_stage(
    backend: str,
    stage: str,
    design_name: str,
    design_config: str,
    pdk: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    be = get_backend(backend)
    design = DesignSpec(
        name=design_name,
        config_path=Path(design_config),
        pdk=pdk,
    )
    result = be.run_stage(stage, design, params or {})

    # Persist run to DB
    run_db_id = _upsert_run(result, design)

    # Parse and ingest reports if the stage succeeded
    if result.status.value == "success":
        reports = be.collect_reports(result)
        for rpt in reports:
            try:
                parser = get_parser(rpt.report_type)
                records = parser.parse_file(rpt.path)
                _ingest_records(records, run_db_id, rpt.stage)
            except Exception:
                logger.exception("Failed to parse %s", rpt.path)

        # Archive the run data to Parquet (best-effort; never fails the main flow)
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
        "error": result.error_message,
    }


def _query_timing(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    with get_db() as db:
        conditions = ["d.name = :design_name"]
        params: dict[str, Any] = {"design_name": design_name, "limit": limit}
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if run_id:
            conditions.append("r.id = :run_id")
            params["run_id"] = run_id
        where = " AND ".join(conditions)
        summary_rows = db.execute(
            text(
                f"""
                SELECT ts.id, r.id AS run_id, r.stage, b.name AS backend,
                       ts.view, ts.wns_ns, ts.tns_ns, ts.failing_endpoints,
                       r.params, r.created_at
                FROM timing_summary ts
                JOIN runs r    ON r.id  = ts.run_id
                JOIN designs d ON d.id  = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()

        # Query individual timing paths (worst slack paths)
        path_rows = db.execute(
            text(
                f"""
                SELECT tp.id, tp.run_id, tp.startpoint, tp.endpoint,
                       tp.path_group, tp.slack_ns
                FROM timing_paths tp
                JOIN runs r ON r.id = tp.run_id
                JOIN designs d ON d.id = r.design_id
                WHERE {where}
                ORDER BY tp.slack_ns ASC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()

    return {
        "summary": [dict(r) for r in summary_rows],
        "paths": [dict(r) for r in path_rows],
    }


def _query_congestion(
    run_id: int,
    x1: float | None = None,
    y1: float | None = None,
    x2: float | None = None,
    y2: float | None = None,
) -> list[dict[str, Any]]:
    with get_db() as db:
        if all(v is not None for v in [x1, y1, x2, y2]):
            bbox_wkt = f"POLYGON(({x1} {y1},{x2} {y1},{x2} {y2},{x1} {y2},{x1} {y1}))"
            rows = db.execute(
                text(
                    """
                    SELECT id, run_id, overflow, layer,
                           ST_AsText(geom) AS geom_wkt
                    FROM congestion_hotspots
                    WHERE run_id = :run_id
                      AND ST_Intersects(geom, ST_GeomFromText(:bbox, 0))
                    ORDER BY overflow DESC
                    """
                ),
                {"run_id": run_id, "bbox": bbox_wkt},
            ).mappings().fetchall()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT id, run_id, overflow, layer,
                           ST_AsText(geom) AS geom_wkt
                    FROM congestion_hotspots
                    WHERE run_id = :run_id
                    ORDER BY overflow DESC
                    LIMIT 20
                    """
                ),
                {"run_id": run_id},
            ).mappings().fetchall()
    return [dict(r) for r in rows]


def _compare_runs(run_id_a: int, run_id_b: int) -> dict[str, Any]:
    with get_db() as db:
        def _fetch(rid: int) -> dict:
            row = db.execute(
                text(
                    """
                    SELECT r.id, r.stage, r.params, r.status,
                           b.name AS backend, d.name AS design,
                           ts.wns_ns, ts.tns_ns, ts.failing_endpoints
                    FROM runs r
                    JOIN backends b ON b.id = r.backend_id
                    JOIN designs d ON d.id = r.design_id
                    LEFT JOIN timing_summary ts ON ts.run_id = r.id
                    WHERE r.id = :rid
                    ORDER BY ts.wns_ns ASC
                    LIMIT 1
                    """
                ),
                {"rid": rid},
            ).mappings().first()
            return dict(row) if row else {}

        a = _fetch(run_id_a)
        b = _fetch(run_id_b)

    diff: dict[str, Any] = {"run_a": a, "run_b": b, "delta": {}}
    for metric in ("wns_ns", "tns_ns", "failing_endpoints"):
        va, vb = a.get(metric), b.get(metric)
        if va is not None and vb is not None:
            diff["delta"][metric] = round(vb - va, 6)
    return diff


def _query_utilization(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    with get_db() as db:
        conditions = ["d.name = :design_name"]
        params: dict[str, Any] = {"design_name": design_name, "limit": limit}
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if run_id:
            conditions.append("r.id = :run_id")
            params["run_id"] = run_id
        where = " AND ".join(conditions)
        rows = db.execute(
            text(
                f"""
                SELECT us.id, r.id AS run_id, r.stage, b.name AS backend,
                       us.design_area_um2, us.utilization_pct,
                       us.num_cells, us.num_registers, r.created_at
                FROM utilization_summary us
                JOIN runs r    ON r.id  = us.run_id
                JOIN designs d ON d.id  = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def _query_power(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    with get_db() as db:
        conditions = ["d.name = :design_name"]
        params: dict[str, Any] = {"design_name": design_name, "limit": limit}
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if run_id:
            conditions.append("r.id = :run_id")
            params["run_id"] = run_id
        where = " AND ".join(conditions)
        rows = db.execute(
            text(
                f"""
                SELECT ps.id, r.id AS run_id, r.stage, b.name AS backend,
                       ps.internal_power_w, ps.switching_power_w,
                       ps.leakage_power_w, ps.total_power_w, r.created_at
                FROM power_summary ps
                JOIN runs r    ON r.id  = ps.run_id
                JOIN designs d ON d.id  = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def _suggest_params(run_id: int, target_spec: str) -> dict[str, Any]:
    """LLM-backed parameter suggestions with heuristic fallback."""
    # ── Gather current run metrics ────────────────────────────────────────────
    with get_db() as db:
        ts_row = db.execute(
            text(
                "SELECT wns_ns, tns_ns, failing_endpoints "
                "FROM timing_summary WHERE run_id = :rid "
                "ORDER BY wns_ns ASC LIMIT 1"
            ),
            {"rid": run_id},
        ).mappings().first()

        run_row = db.execute(
            text(
                "SELECT r.params, r.stage, d.name AS design_name, d.pdk "
                "FROM runs r JOIN designs d ON d.id = r.design_id WHERE r.id = :rid"
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

        # Fetch the last 5 runs for the same design to provide history
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

    # ── Try LLM-backed suggestions ────────────────────────────────────────────
    try:
        suggestions = _llm_suggest_params(
            run_id=run_id,
            target_spec=target_spec,
            ts_row=dict(ts_row) if ts_row else {},
            run_row=dict(run_row) if run_row else {},
            us_row=dict(us_row) if us_row else {},
            history=[dict(r) for r in history_rows],
        )
        return {**suggestions, "run_id": run_id, "target_spec": target_spec, "source": "llm"}
    except Exception:
        logger.warning("LLM suggest_params failed; falling back to heuristics", exc_info=True)

    # ── Heuristic fallback ────────────────────────────────────────────────────
    suggestions_h: dict[str, Any] = {}
    reasoning: list[str] = []

    if ts_row:
        wns = ts_row["wns_ns"] or 0.0
        if wns < -0.5:
            suggestions_h["CLOCK_PERIOD"] = "increase by 0.5 ns"
            reasoning.append(f"WNS={wns:.3f}ns is highly negative; relax clock period.")
        elif wns < -0.1:
            suggestions_h["TNS_END_PERCENT"] = 20
            reasoning.append(f"WNS={wns:.3f}ns; tighten TNS endpoint coverage.")
        if ts_row["failing_endpoints"] and ts_row["failing_endpoints"] > 10:
            suggestions_h["CORE_UTILIZATION"] = "reduce by 5%"
            reasoning.append("High FEP; consider reducing core utilization to ease placement.")

    return {
        "run_id": run_id,
        "target_spec": target_spec,
        "suggested_params": suggestions_h,
        "reasoning": reasoning,
        "source": "heuristic",
    }


def _llm_suggest_params(
    run_id: int,
    target_spec: str,
    ts_row: dict,
    run_row: dict,
    us_row: dict,
    history: list[dict],
) -> dict[str, Any]:
    """Call the MiniMax LLM to produce parameter suggestions.

    Raises an exception if the LLM call fails so the caller can fall back.
    """
    context_parts = [
        f"Design: {run_row.get('design_name', 'unknown')}  PDK: {run_row.get('pdk', 'unknown')}",
        f"Stage: {run_row.get('stage', 'unknown')}",
        f"Current params: {json.dumps(run_row.get('params') or {})}",
        "",
        "## Current run metrics",
    ]
    if ts_row:
        context_parts.append(
            f"  Timing – WNS: {ts_row.get('wns_ns')} ns, "
            f"TNS: {ts_row.get('tns_ns')} ns, "
            f"Failing endpoints: {ts_row.get('failing_endpoints')}"
        )
    if us_row:
        context_parts.append(
            f"  Utilization – Area: {us_row.get('design_area_um2')} µm², "
            f"Util%: {us_row.get('utilization_pct')}, "
            f"Cells: {us_row.get('num_cells')}"
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

    system_prompt = (
        "You are an expert EDA physical design engineer specialised in VLSI PPA optimisation "
        "with OpenROAD Flow Scripts (ORFS). "
        "Given current metrics and run history, output ONLY a JSON object with two keys:\n"
        '  "suggested_params": an object mapping ORFS make variable names to values,\n'
        '  "reasoning": an array of concise strings explaining each suggestion.\n'
        "Do NOT include any other text outside the JSON object."
    )
    user_msg = (
        f"PPA target: {target_spec}\n\n"
        + "\n".join(context_parts)
        + "\n\nSuggest ORFS parameter changes to reach the PPA target."
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

    transport = httpx.HTTPTransport()
    with httpx.Client(timeout=60, transport=transport) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    # Strip possible markdown code fence
    content = content.strip()
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


def _tune_ppa(
    backend: str,
    stage: str,
    design_name: str,
    design_config: str,
    pdk: str,
    target_spec: str,
    max_iterations: int = 5,
) -> dict[str, Any]:
    """Autonomous PPA tuning loop.

    For each iteration:
    1. Run the EDA stage with current parameters.
    2. Query timing metrics from the DB.
    3. Check whether the target spec is satisfied.
    4. If not, call ``suggest_params`` to get the next set of parameters.
    5. Repeat until the target is met or ``max_iterations`` is exhausted.
    """
    history: list[dict[str, Any]] = []
    current_params: dict[str, Any] = {}

    for iteration in range(1, max_iterations + 1):
        logger.info("tune_ppa iteration %d/%d params=%s", iteration, max_iterations, current_params)

        # Step 1 – run the stage
        run_result = _run_eda_stage(
            backend=backend,
            stage=stage,
            design_name=design_name,
            design_config=design_config,
            pdk=pdk,
            params=current_params,
        )

        run_db_id = run_result.get("run_id")
        status = run_result.get("status")

        iteration_record: dict[str, Any] = {
            "iteration": iteration,
            "params": current_params,
            "run_id": run_db_id,
            "status": status,
            "target_met": False,
        }

        if status != "success" or run_db_id is None:
            iteration_record["error"] = run_result.get("error")
            history.append(iteration_record)
            break

        # Step 2 – query timing
        timing = _query_timing(design_name, stage=stage, run_id=run_db_id, limit=1)
        summary = timing.get("summary", [])
        if summary:
            iteration_record["wns_ns"] = summary[0].get("wns_ns")
            iteration_record["tns_ns"] = summary[0].get("tns_ns")
            iteration_record["failing_endpoints"] = summary[0].get("failing_endpoints")

        # Step 3 – check target
        target_met = _check_ppa_target(timing, target_spec)
        iteration_record["target_met"] = target_met
        history.append(iteration_record)

        if target_met:
            logger.info("tune_ppa: target met at iteration %d", iteration)
            break

        if iteration < max_iterations:
            # Step 4 – get next params
            suggestion = _suggest_params(run_db_id, target_spec)
            raw_params = suggestion.get("suggested_params", {})
            # Only keep concrete k=v pairs (skip "increase by …" strings)
            current_params = {
                k: v
                for k, v in raw_params.items()
                if not isinstance(v, str) or v.replace(".", "").isdigit()
            }

    return {
        "iterations_run": len(history),
        "target_spec": target_spec,
        "target_met": any(r.get("target_met") for r in history),
        "history": history,
    }


def _check_ppa_target(timing: dict[str, Any], target_spec: str) -> bool:
    """Evaluate a simple natural-language PPA target against timing data.

    Supports patterns like 'WNS >= -0.1' (case-insensitive).
    Returns True if the target is satisfied (or if it cannot be parsed).
    """
    import re

    summary = timing.get("summary", [])
    if not summary:
        return False

    latest = summary[0]
    spec_lower = target_spec.lower()

    wns_match = re.search(r"wns\s*(>=|<=|>|<|==)\s*(-?[\d.]+)", spec_lower)
    if wns_match:
        op, threshold = wns_match.group(1), float(wns_match.group(2))
        wns = latest.get("wns_ns")
        if wns is None:
            return False
        if op == ">=" and wns >= threshold:
            return True
        if op == "<=" and wns <= threshold:
            return True
        if op == ">" and wns > threshold:
            return True
        if op == "<" and wns < threshold:
            return True
        if op == "==" and wns == threshold:
            return True
        return False

    # No parseable spec → consider target met if there are 0 failing endpoints
    return (latest.get("failing_endpoints") or 0) == 0


# ── Dispatch table ────────────────────────────────────────────────────────────

_TOOL_DISPATCH = {
    "run_eda_stage": _run_eda_stage,
    "query_timing": _query_timing,
    "query_congestion": _query_congestion,
    "query_utilization": _query_utilization,
    "query_power": _query_power,
    "compare_runs": _compare_runs,
    "suggest_params": _suggest_params,
    "tune_ppa": _tune_ppa,
}


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name with *arguments* and return a JSON string."""
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**arguments)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(exc)})


# ── Internal DB helpers ───────────────────────────────────────────────────────

def _upsert_run(result: Any, design: DesignSpec) -> int:
    """Insert the RunResult into the DB and return the integer PK."""

    with get_db() as db:
        # Ensure backend exists
        backend_row = db.execute(
            text("SELECT id FROM backends WHERE name = :name"),
            {"name": result.backend_name},
        ).first()
        backend_id = backend_row[0] if backend_row else None
        if backend_id is None:
            db.execute(
                text("INSERT INTO backends (name, version) VALUES (:name, :ver)"),
                {"name": result.backend_name, "ver": "unknown"},
            )
            backend_id = db.execute(
                text("SELECT id FROM backends WHERE name = :name"),
                {"name": result.backend_name},
            ).scalar()

        # Ensure design exists
        design_row = db.execute(
            text("SELECT id FROM designs WHERE name = :name AND pdk = :pdk"),
            {"name": design.name, "pdk": design.pdk},
        ).first()
        design_id = design_row[0] if design_row else None
        if design_id is None:
            db.execute(
                text(
                    "INSERT INTO designs (name, pdk, config_path) "
                    "VALUES (:name, :pdk, :cfg)"
                ),
                {"name": design.name, "pdk": design.pdk, "cfg": str(design.config_path)},
            )
            design_id = db.execute(
                text("SELECT id FROM designs WHERE name = :name AND pdk = :pdk"),
                {"name": design.name, "pdk": design.pdk},
            ).scalar()

        db.execute(
            text(
                """
                INSERT INTO runs
                    (run_uuid, backend_id, design_id, stage, status, params,
                     log_path, report_dir, error_message, started_at, finished_at)
                VALUES
                    (:uuid, :bid, :did, :stage, :status, :params,
                     :log_path, :report_dir, :error, :started, :finished)
                """
            ),
            {
                "uuid": result.run_id,
                "bid": backend_id,
                "did": design_id,
                "stage": result.stage,
                "status": result.status.value,
                "params": json.dumps(result.params),
                "log_path": str(result.log_path or ""),
                "report_dir": str(result.report_dir or ""),
                "error": result.error_message,
                "started": result.started_at,
                "finished": result.finished_at,
            },
        )
        run_id = db.execute(
            text("SELECT id FROM runs WHERE run_uuid = :uuid"),
            {"uuid": result.run_id},
        ).scalar()
    return run_id


def _ingest_records(records: list[dict], run_id: int, stage: str) -> None:
    """Fan out parsed records into the appropriate DB tables."""
    with get_db() as db:
        for rec in records:
            kind = rec.get("kind")
            if kind == "summary" and "wns_ns" in rec:
                db.execute(
                    text(
                        "INSERT INTO timing_summary "
                        "(run_id, view, wns_ns, tns_ns, failing_endpoints) "
                        "VALUES (:run_id, :view, :wns, :tns, :fep)"
                    ),
                    {
                        "run_id": run_id,
                        "view": rec.get("view", "default"),
                        "wns": rec.get("wns_ns"),
                        "tns": rec.get("tns_ns"),
                        "fep": rec.get("failing_endpoints"),
                    },
                )
            elif kind == "path":
                db.execute(
                    text(
                        "INSERT INTO timing_paths "
                        "(run_id, startpoint, endpoint, path_group, slack_ns) "
                        "VALUES (:run_id, :sp, :ep, :pg, :slack)"
                    ),
                    {
                        "run_id": run_id,
                        "sp": rec.get("startpoint", ""),
                        "ep": rec.get("endpoint", ""),
                        "pg": rec.get("path_group"),
                        "slack": rec.get("slack_ns", 0.0),
                    },
                )
            elif kind == "hotspot":
                db.execute(
                    text(
                        "INSERT INTO congestion_hotspots "
                        "(run_id, geom, overflow) "
                        "VALUES (:run_id, ST_GeomFromText(:wkt, 0), :overflow)"
                    ),
                    {
                        "run_id": run_id,
                        "wkt": rec["wkt"],
                        "overflow": rec.get("overflow", 0),
                    },
                )
            elif kind == "orfs_violation":
                # ORFS violation records from congestion-*.rpt files
                wkt = rec.get("wkt")
                if not wkt:
                    continue  # Skip violations without bounding box
                db.execute(
                    text(
                        "INSERT INTO congestion_hotspots "
                        "(run_id, geom, overflow, layer) "
                        "VALUES (:run_id, ST_GeomFromText(:wkt, 0), :overflow, :layer)"
                    ),
                    {
                        "run_id": run_id,
                        "wkt": wkt,
                        "overflow": rec.get("overflow", 0),
                        "layer": rec.get("layer"),
                    },
                )
            elif kind == "summary" and "design_area_um2" in rec:
                db.execute(
                    text(
                        "INSERT INTO utilization_summary "
                        "(run_id, design_area_um2, utilization_pct, num_cells, num_registers) "
                        "VALUES (:run_id, :area, :util, :cells, :regs)"
                    ),
                    {
                        "run_id": run_id,
                        "area": rec.get("design_area_um2"),
                        "util": rec.get("utilization_pct"),
                        "cells": rec.get("num_cells"),
                        "regs": rec.get("num_registers"),
                    },
                )
            elif kind == "summary" and "total_power_w" in rec:
                db.execute(
                    text(
                        "INSERT INTO power_summary "
                        "(run_id, internal_power_w, switching_power_w, "
                        "leakage_power_w, total_power_w) "
                        "VALUES (:run_id, :int, :sw, :lk, :tot)"
                    ),
                    {
                        "run_id": run_id,
                        "int": rec.get("internal_power_w"),
                        "sw": rec.get("switching_power_w"),
                        "lk": rec.get("leakage_power_w"),
                        "tot": rec.get("total_power_w"),
                    },
                )
            elif kind == "summary" and "total_violations" in rec:
                db.execute(
                    text(
                        "INSERT INTO drc_violations "
                        "(run_id, violation_type, total_violations) "
                        "VALUES (:run_id, 'SUMMARY', :total)"
                    ),
                    {"run_id": run_id, "total": rec.get("total_violations")},
                )
            elif kind == "drc_violation":
                db.execute(
                    text(
                        "INSERT INTO drc_violations "
                        "(run_id, violation_type, layer, nets, bbox_wkt) "
                        "VALUES (:run_id, :vtype, :layer, :nets, :bbox)"
                    ),
                    {
                        "run_id": run_id,
                        "vtype": rec.get("violation_type", ""),
                        "layer": rec.get("layer"),
                        "nets": json.dumps(rec.get("nets") or []),
                        "bbox": rec.get("bbox_wkt"),
                    },
                )
