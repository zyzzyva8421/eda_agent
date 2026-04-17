"""Agent tool definitions and implementations.

Each tool is exposed to the LLM as an OpenAI-style function-call tool.
The ``TOOL_SCHEMAS`` list contains the JSON schema for every tool.
The ``execute_tool`` dispatcher routes a function-call name → implementation.

Tools
-----
run_eda_stage       – invoke a backend stage
query_timing        – query timing metrics from the DB
query_congestion    – spatial congestion query via PostGIS
compare_runs        – diff PPA between two runs
suggest_params      – LLM-assisted parameter suggestion based on history
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec
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
                "Query timing results (WNS, TNS, failing endpoints) from the "
                "database for a specific design, stage, and optional run_id."
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
    return [dict(r) for r in rows]


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


def _suggest_params(run_id: int, target_spec: str) -> dict[str, Any]:
    """Heuristic parameter suggestions based on current timing/congestion."""
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
            text("SELECT params, stage FROM runs WHERE id = :rid"),
            {"rid": run_id},
        ).mappings().first()

    suggestions: dict[str, Any] = {}
    reasoning: list[str] = []

    if ts_row:
        wns = ts_row["wns_ns"] or 0.0
        if wns < -0.5:
            suggestions["CLOCK_PERIOD"] = "increase by 0.5 ns"
            reasoning.append(f"WNS={wns:.3f}ns is highly negative; relax clock period.")
        elif wns < -0.1:
            suggestions["TNS_END_PERCENT"] = 20
            reasoning.append(f"WNS={wns:.3f}ns; tighten TNS endpoint coverage.")
        if ts_row["failing_endpoints"] and ts_row["failing_endpoints"] > 10:
            suggestions["CORE_UTILIZATION"] = "reduce by 5%"
            reasoning.append("High FEP; consider reducing core utilization to ease placement.")

    return {
        "run_id": run_id,
        "target_spec": target_spec,
        "suggested_params": suggestions,
        "reasoning": reasoning,
    }


# ── Dispatch table ────────────────────────────────────────────────────────────

_TOOL_DISPATCH = {
    "run_eda_stage": _run_eda_stage,
    "query_timing": _query_timing,
    "query_congestion": _query_congestion,
    "compare_runs": _compare_runs,
    "suggest_params": _suggest_params,
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
    from eda_agent.db.schema import Backend, Design, Run

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
