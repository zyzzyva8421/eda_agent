"""Agent tool definitions and implementations.

Each tool is exposed to the LLM as an OpenAI-style function-call tool.
The ``TOOL_SCHEMAS`` list contains the JSON schema for every tool.
The ``execute_tool`` dispatcher routes a function-call name → implementation.

Tools
-----
run_eda_stage       – invoke a backend stage
run_eda_flow        – run a sequence of EDA stages (synth → finish)
submit_job          – submit an async job to the background queue
job_status         – check async job status
job_logs           – fetch logs from an async job
cancel_job         – cancel a pending async job
query_timing        – query timing metrics from the DB
query_congestion    – spatial congestion query (WKT bbox filtering)
query_utilization   – query cell area / utilization metrics from the DB
query_power        – query power breakdown metrics from the DB
compare_runs       – diff PPA between two runs
suggest_params     – LLM-assisted parameter suggestion based on history
tune_ppa          – autonomous PPA tuning loop (suggest → run → repeat)
tune_ppa_multistage – multi-stage autonomous PPA tuning
infer_root_cause  – rule-based root cause inference
confirm_root_cause – confirm root cause and save to case memory
save_case         – persist a debugging case to case memory

All tool calls are intercepted by the guardrail layer before execution.
See :mod:`eda_agent.agent.guardrails` for the risk policy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from eda_agent.agent.param_mapper import PARAM_MAPPER, OptimizationObjective
from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec
from eda_agent.config import settings
from eda_agent.db.session import get_db
from eda_agent.parsers import get_parser
from eda_agent.tracing import is_tracing_enabled, trace_chat

logger = logging.getLogger(__name__)


def _ensure_worker_running() -> None:
    """Start queue worker if not already running.

    Natural-language flow uses tool calls directly (not CLI subcommands), so we
    need to ensure the worker exists here as well.
    """
    from eda_agent.queue.worker import _WORKER_LOG, is_worker_running

    if is_worker_running():
        return

    env = os.environ.copy()
    env["ORFS_ROOT"] = str(settings.orfs_root)
    env["POSTGRES_HOST"] = settings.postgres_host
    env["POSTGRES_PORT"] = str(settings.postgres_port)
    env["POSTGRES_USER"] = settings.postgres_user
    env["POSTGRES_PASSWORD"] = settings.postgres_password
    env["POSTGRES_DB"] = settings.postgres_db

    _WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_WORKER_LOG, "a") as log_fh:
        subprocess.Popen(
            ["eda-agent-worker"],
            stdout=log_fh,
            stderr=log_fh,
            close_fds=True,
            start_new_session=True,
            env=env,
        )

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
                        "description": "Backend name: 'orfs', 'innovus', 'icc2', or custom. 如果用户提到 'place' 但没有指定 backend，默认使用 'innovus'。",
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
                "required": ["backend", "stage", "design_name"],
            },
        },
        # 注：design_config 和 pdk 对某些 backend（如 innovus）可从 settings 自动获取
    },
    {
        "type": "function",
        "function": {
            "name": "run_eda_flow",
            "description": (
                "Run a sequence of EDA flow stages (e.g. from synth to finish) for a "
                "given design. Stages run sequentially in order. Returns status for each stage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name: 'orfs', 'innovus', 'icc2', or custom.",
                    },
                    "stage_start": {
                        "type": "string",
                        "description": "Starting stage (e.g. 'synth') or 'all' to run all stages.",
                    },
                    "stage_end": {
                        "type": "string",
                        "description": "Ending stage (e.g. 'finish'). Ignored if stage_start='all'.",
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
                    "clean": {
                        "type": "boolean",
                        "description": "If true, run 'make clean' before starting to force rerun all stages.",
                    },
                },
                "required": ["backend", "stage_start", "design_name"],
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
            "name": "query_congestion_summary",
            "description": (
                "Query congestion summary metrics for a run (total overflow, horizontal/vertical "
                "overflow percentages) parsed from Innovus congestion reports."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
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
            "name": "add_placement_blockage",
            "description": (
                "Apply one or more Innovus placement blockages (soft/hard/partial) on the remote "
                "design state and persist them for subsequent place runs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "blockages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "x1": {"type": "number"},
                                "y1": {"type": "number"},
                                "x2": {"type": "number"},
                                "y2": {"type": "number"},
                                "type": {
                                    "type": "string",
                                    "description": "Blockage type: soft/hard/partial.",
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["x1", "y1", "x2", "y2"],
                        },
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Optional remote Innovus workdir override.",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage whose output_dir should host blockages.tcl (default: place).",
                    },
                },
                "required": ["run_id", "blockages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tune_congestion_with_blockage",
            "description": (
                "Iteratively run Innovus place, evaluate congestion summary, let the LLM decide "
                "placement blockages from hotspots, and repeat until overflow target is met."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {"type": "string"},
                    "design_name": {"type": "string"},
                    "design_config": {"type": "string"},
                    "pdk": {"type": "string"},
                    "congestion_threshold_pct": {
                        "type": "number",
                        "description": "Target max of horizontal/vertical overflow percentage.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum tuning iterations.",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Optional Innovus remote workdir override.",
                    },
                },
                "required": ["backend", "design_name"],
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
    {
        "type": "function",
        "function": {
            "name": "get_run_log",
            "description": (
                "Read the log file from a failed or successful EDA run to diagnose issues. "
                "Returns the last N lines of the log file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "integer",
                        "description": "Run ID to read log from.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of last lines to return (default 50).",
                    },
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tune_ppa_multistage",
            "description": (
                "Multi-stage autonomous PPA tuning loop. Unlike tune_ppa (which repeats a "
                "single fixed stage), this tool analyses which stage is the bottleneck "
                "(based on setup/hold violations, congestion, DRC counts) and re-runs "
                "the flow from that stage with adjusted parameters. Returns the full "
                "iteration history with per-stage metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name (e.g. 'orfs').",
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
                    "start_stage": {
                        "type": "string",
                        "description": (
                            "Earliest stage to run in the first pass "
                            "(default 'place'). Upstream stages (synth/floorplan) "
                            "are assumed already done."
                        ),
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum tuning iterations (default 5).",
                    },
                },
                "required": [
                    "backend", "design_name", "design_config", "pdk", "target_spec",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_job",
            "description": (
                "Submit an EDA job to the asynchronous queue for background execution. "
                "Returns a job_id immediately while the job runs in the background worker. "
                "Use 'job_status' to poll for completion. "
                "Set run_mode='flow' to run a sequence of stages (e.g. 'all' from synth to finish)."
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
                        "description": "Flow stage to execute (e.g. 'synth', 'place', 'route'). Ignored if run_mode='flow'.",
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
                        "description": "Key-value EDA parameters (optional).",
                    },
                    "stage_start": {
                        "type": "string",
                        "description": "Starting stage for flow mode (e.g. 'synth', 'all').",
                    },
                    "stage_end": {
                        "type": "string",
                        "description": "Ending stage for flow mode (e.g. 'finish').",
                    },
                    "run_mode": {
                        "type": "string",
                        "description": "Execution mode: 'stage' (single stage) or 'flow' (sequence of stages). Default: 'stage'.",
                    },
                },
                "required": ["backend", "design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_status",
            "description": (
                "Check the status of a previously submitted async job. "
                "Returns the job status, run_id (if completed), and error message if failed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned from submit_job.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_logs",
            "description": (
                "Fetch the log file from a background job. "
                "Returns the last N lines of the log."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned from submit_job.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of last lines to return (default 50).",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_job",
            "description": (
                "Cancel a pending or running background job. "
                "Returns whether the cancellation succeeded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned from submit_job.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_case",
            "description": (
                "Save a resolved debugging case to persistent memory. "
                "Call this AFTER diagnosing a root cause so the knowledge can "
                "be retrieved in future sessions with similar problems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {
                        "type": "string",
                        "description": "Top-level design name (e.g. 'gcd').",
                    },
                    "pdk": {
                        "type": "string",
                        "description": "PDK identifier (e.g. 'sky130hd').",
                    },
                    "symptoms": {
                        "type": "string",
                        "description": (
                            "Free-text description of the observed problems "
                            "(timing violations, congestion, DRC errors, etc.)."
                        ),
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "The diagnosed root cause of the problems.",
                    },
                    "actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of actions taken to fix the issue.",
                    },
                    "result_metrics": {
                        "type": "object",
                        "description": (
                            "Key QoR metrics before and after the fix, e.g. "
                            "{\"wns_before\": -0.5, \"wns_after\": -0.1}."
                        ),
                    },
                },
                "required": ["symptoms", "root_cause"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "infer_root_cause",
            "description": (
                "Run the rule-based root cause inference engine against a specific "
                "EDA run and return ranked root cause hypotheses with evidence and "
                "experiment suggestions. Call this when the user asks WHY a run is "
                "failing or wants to diagnose timing/congestion/DRC issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "integer",
                        "description": "DB run id (runs.id) to diagnose.",
                    },
                    "symptoms": {
                        "type": "string",
                        "description": (
                            "Optional free-text description of the observed problems "
                            "(e.g. 'WNS is -0.5ns and there are many congestion hotspots'). "
                            "Stored alongside the inference record."
                        ),
                    },
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_root_cause",
            "description": (
                "Confirm the engineer-approved root cause for a previous inference. "
                "Persists the result to case memory so it can be retrieved in future "
                "sessions. Call this AFTER the engineer agrees with a hypothesis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inference_id": {
                        "type": "integer",
                        "description": "inference_id returned by infer_root_cause.",
                    },
                    "confirmed_cause_id": {
                        "type": "string",
                        "description": (
                            "The cause_id to confirm (e.g. 'routing_detour'). "
                            "Must match one of the cause_id values in the hypotheses list, "
                            "or a free-text string if none matched."
                        ),
                    },
                },
                "required": ["inference_id", "confirmed_cause_id"],
            },
        },
    },
]


# ── Tool implementations ──────────────────────────────────────────────────────


def _run_eda_stage(
    backend: str,
    stage: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # 对于 innovus，可以从 settings 自动获取配置
    if not backend:
        # 根据 stage 名称自动推断 backend
        if stage in ("place", "cts", "route", "floorplan", "powerplan", "prects", "postcts", "postroute", "signoff"):
            backend = "innovus"
        else:
            backend = "orfs"
    
    if backend.lower() == "innovus":
        from eda_agent.config import settings
        if not design_config:
            design_config = settings.innovus_remote_workdir
        if not pdk:
            pdk = "tsmc18"
    
    if not design_config:
        raise ValueError("design_config is required. For innovus, set INNOVUS_REMOTE_WORKDIR in config.")
    if not pdk:
        raise ValueError("pdk is required. For innovus, default is tsmc18.")

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
        try:
            _upsert_artifacts(run_db_id, reports)
        except Exception:
            logger.debug("Failed to upsert artifacts for run %s", run_db_id, exc_info=True)
        for rpt in reports:
            try:
                parser = get_parser(rpt.report_type)
                records = parser.parse_file(rpt.path)
                _ingest_records(records, run_db_id, rpt.stage)
            except Exception as e:
                # Best-effort: don't fail the run for parse errors
                logger.debug("Failed to parse %s: %s", rpt.path, e)

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
        "design_name": design_name,
        "pdk": pdk,
        "error": result.error_message,
        "log_path": str(result.log_path) if result.log_path else None,
    }


def _run_eda_flow_sync(
    backend: str,
    stage_start: str,
    design_name: str,
    design_config: str,
    pdk: str,
    stage_end: str | None = None,
    params: dict[str, Any] | None = None,
    clean: bool = False,
) -> dict[str, Any]:
    """Run a sequence of EDA flow stages."""
    # Handle clean flag - run make clean first if requested
    if clean:
        be = get_backend(backend)
        design = DesignSpec(
            name=design_name,
            config_path=Path(design_config),
            pdk=pdk,
        )
        # Import and run clean
        import subprocess
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

    # Get supported stages and determine which to run
    supported_stages = be.get_supported_stages()

    # Handle "all" keyword or build stage range
    if stage_start.lower() == "all":
        stages_to_run = supported_stages
    elif stage_end:
        try:
            start_idx = supported_stages.index(stage_start.lower())
            end_idx = supported_stages.index(stage_end.lower())
            if start_idx > end_idx:
                return {"error": f"Stage '{stage_start}' comes after '{stage_end}'"}
            stages_to_run = supported_stages[start_idx : end_idx + 1]
        except ValueError as e:
            return {"error": f"Invalid stage name: {e}"}
    else:
        # Single stage - just run one
        if stage_start.lower() not in supported_stages:
            return {
                "error": f"Stage '{stage_start}' not supported. Valid: {supported_stages}"
            }
        stages_to_run = [stage_start.lower()]

    # Run stages sequentially
    results = []
    for stage in stages_to_run:
        stage_result = be.run_stage(stage, design, params or {})
        run_db_id = _upsert_run(stage_result, design)

        # Parse reports if successful
        if stage_result.status.value == "success":
            reports = be.collect_reports(stage_result)
            try:
                _upsert_artifacts(run_db_id, reports)
            except Exception:
                logger.debug("Failed to upsert artifacts for run %s", run_db_id, exc_info=True)
            for rpt in reports:
                try:
                    parser = get_parser(rpt.report_type)
                    records = parser.parse_file(rpt.path)
                    _ingest_records(records, run_db_id, rpt.stage)
                except Exception as e:
                    # Best-effort: don't fail the flow for parse errors
                    # (some stages like floorplan may not have certain report types)
                    logger.debug("Failed to parse %s: %s", rpt.path, e)

            # Archive to Parquet (best-effort)
            try:
                from eda_agent.db.archiver import archive_run
                archive_run(run_db_id)
            except Exception:
                logger.warning("Parquet archival failed for run %d", run_db_id)

        results.append({
            "stage": stage,
            "status": stage_result.status.value,
            "run_id": run_db_id,
            "run_uuid": stage_result.run_id,
            "error": stage_result.error_message,
            "log_path": str(stage_result.log_path) if stage_result.log_path else None,
        })

    # Determine overall status
    all_success = all(r["status"] == "success" for r in results)
    overall_status = "success" if all_success else "partial_failure"

    return {
        "overall_status": overall_status,
        "stages_run": len(results),
        "design_name": design_name,
        "pdk": pdk,
        "results": results,
    }


def _run_eda_flow(
    backend: str,
    stage_start: str,
    design_name: str,
    design_config: str,
    pdk: str,
    stage_end: str | None = None,
    params: dict[str, Any] | None = None,
    clean: bool = False,
) -> dict[str, Any]:
    """Submit a flow job asynchronously to keep CLI interactive.

    NOTE: Synchronous flow execution is implemented by ``_run_eda_flow_sync``
    and is used by the background worker.
    """
    # Handle clean flag for forcing rerun
    if clean:
        params = params or {}
        params["_clean"] = True

    # Keep tool-facing behavior non-blocking: return job_id immediately.
    return _submit_job(
        backend=backend,
        stage=stage_start,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        params=params,
        stage_start=stage_start,
        stage_end=stage_end,
        run_mode="flow",
    )


# ── Async job queue tools ───────────────────────────────────────────────────


def _submit_job(
    backend: str,
    design_name: str,
    design_config: str,
    pdk: str,
    stage: str | None = None,
    params: dict[str, Any] | None = None,
    stage_start: str | None = None,
    stage_end: str | None = None,
    run_mode: str = "stage",
) -> dict[str, Any]:
    """Submit an async job to the queue (stage or flow mode)."""
    from eda_agent.queue.store import JobStore

    if run_mode not in ("stage", "flow"):
        return {"error": f"Invalid run_mode '{run_mode}'. Use 'stage' or 'flow'."}

    if run_mode == "stage" and not stage:
        return {"error": "'stage' is required when run_mode='stage'"}

    # The queue schema requires a non-null stage. In flow mode we store an
    # informational stage value and use stage_start/stage_end for execution.
    effective_stage = stage or stage_start or "all"

    store = JobStore()
    job_id = store.enqueue(
        backend=backend,
        stage=effective_stage,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        params=params or {},
        stage_start=stage_start,
        stage_end=stage_end,
        run_mode=run_mode,
    )

    # Auto-start worker for tool-driven submissions (interactive NL path).
    try:
        _ensure_worker_running()
    except Exception:
        logger.warning("Failed to auto-start worker after job submission", exc_info=True)

    return {
        "job_id": job_id,
        "status": "pending",
        "message": f"Job {job_id} submitted ({run_mode} mode). Use job_status to poll.",
    }


def _job_status(job_id: str) -> dict[str, Any]:
    """Check async job status."""
    from eda_agent.queue.store import JobStore, JobStatus

    store = JobStore()
    job = store.get_job(job_id)
    if job is None:
        return {"error": f"Job {job_id} not found"}

    result: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status.value,
        "backend": job.backend,
        "stage": job.stage,
        "design_name": job.design_name,
    }
    if job.run_db_id is not None:
        result["run_id"] = job.run_db_id
    if job.status in (JobStatus.SUCCESS, JobStatus.FAILED):
        result["error_message"] = job.error_message
        result["log_path"] = job.log_path
    return result


def _job_logs(job_id: str, lines: int = 50) -> dict[str, Any]:
    """Get log file from async job."""
    from eda_agent.queue.store import JobStore

    store = JobStore()
    job = store.get_job(job_id)
    if job is None:
        return {"error": f"Job {job_id} not found"}
    if not job.log_path:
        return {"error": "No log path available for this job"}

    try:
        log_content = Path(job.log_path).read_text()
        log_lines = log_content.splitlines()[-lines:]
        return {"logs": "\n".join(log_lines)}
    except OSError as e:
        return {"error": f"Failed to read log: {e}"}


def _cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a pending/pending_async job."""
    from eda_agent.queue.store import JobStore, JobStatus

    store = JobStore()
    job = store.get_job(job_id)
    if job is None:
        return {"error": f"Job {job_id} not found"}

    if job.status != JobStatus.PENDING:
        return {
            "success": False,
            "error": f"Cannot cancel job in status '{job.status.value}'",
        }

    store.mark_done(job_id, status=JobStatus.CANCELLED, error_message="Cancelled by user")
    return {"success": True, "message": f"Job {job_id} cancelled"}


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
                       ts.fmax_mhz, ts.clock_skew_ns,
                       ts.max_slew_violations, ts.max_fanout_violations,
                       ts.max_cap_violations, ts.setup_violations, ts.hold_violations,
                       ts.critical_path_delay_ns, ts.slack_cpd_ratio_pct,
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
        rows = db.execute(
            text(
                """
                SELECT id, run_id, overflow, layer, geom_wkt
                FROM congestion_hotspots
                WHERE run_id = :run_id
                ORDER BY overflow DESC
                LIMIT 100
                """
            ),
            {"run_id": run_id},
        ).mappings().fetchall()
    result = [dict(r) for r in rows]
    if all(v is not None for v in [x1, y1, x2, y2]):
        def _intersects(row: dict[str, Any]) -> bool:
            bbox = _bbox_from_wkt(row.get("geom_wkt") or "")
            if bbox is None:
                return False
            rx1, ry1, rx2, ry2 = bbox
            return rx1 < x2 and rx2 > x1 and ry1 < y2 and ry2 > y1  # type: ignore[operator]
        result = [r for r in result if _intersects(r)][:20]
    else:
        result = result[:20]
    return result


def _query_congestion_summary(run_id: int) -> dict[str, Any]:
    """Return congestion summary metrics for a run.

    Primary source: parsed Innovus congestion report artifact.
    Fallback: congestion_hotspots aggregates when no summary artifact exists.
    """
    with get_db() as db:
        artifact_row = db.execute(
            text(
                """
                SELECT file_path, artifact_type
                FROM artifacts
                WHERE run_id = :run_id
                  AND artifact_type IN ('innovus_congestion', 'congestion')
                  AND file_path NOT LIKE '%_map.rpt'
                ORDER BY id ASC
                LIMIT 1
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

        if artifact_row:
            file_path = Path(str(artifact_row["file_path"]))
            if file_path.is_file():
                try:
                    parser_name = str(artifact_row["artifact_type"])
                    parser = get_parser(parser_name)
                    records = parser.parse_file(file_path)
                    summary = next((r for r in records if r.get("kind") == "summary"), None)
                    if summary:
                        return {
                            "run_id": run_id,
                            "source": "report",
                            **summary,
                        }
                except Exception:
                    logger.debug(
                        "query_congestion_summary: failed to parse artifact for run_id=%s",
                        run_id,
                        exc_info=True,
                    )

        hotspot_agg = db.execute(
            text(
                """
                SELECT COALESCE(MAX(overflow), 0) AS max_overflow,
                       COALESCE(SUM(overflow), 0) AS sum_overflow,
                       COUNT(*) AS hotspot_count
                FROM congestion_hotspots
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

    if hotspot_agg:
        return {
            "run_id": run_id,
            "source": "hotspot_fallback",
            "kind": "summary",
            "total_overflow": int(hotspot_agg["sum_overflow"] or 0),
            "max_overflow": int(hotspot_agg["max_overflow"] or 0),
            "hotspot_count": int(hotspot_agg["hotspot_count"] or 0),
        }
    return {"run_id": run_id, "error": "No congestion data found"}


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


def _infer_objective_from_target_spec(
    target_spec: str,
    timing_summary: dict[str, Any] | None = None,
) -> OptimizationObjective:
    """Infer the primary optimisation objective from natural-language target text."""
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


def _coerce_innovus_param_value(raw_value: Any, sample_values: list[Any]) -> Any:
    """Coerce LLM/heuristic output into the sample domain expected by PARAM_MAPPER."""
    if isinstance(raw_value, str):
        lowered = raw_value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False

        has_numeric_sample = any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sample_values)
        if has_numeric_sample:
            try:
                numeric = float(raw_value)
                if any(isinstance(v, int) and not isinstance(v, bool) for v in sample_values) and numeric.is_integer():
                    return int(numeric)
                return numeric
            except ValueError:
                return raw_value

    return raw_value


def _filter_suggested_params(
    raw_params: dict[str, Any],
    backend: str,
    stage: str,
) -> dict[str, Any]:
    """Filter suggestions into backend-safe parameter values.

    ORFS keeps the existing numeric-only contract.
    Innovus accepts only parameters defined in PARAM_MAPPER for the given stage,
    including enum / boolean values.
    """
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

        coerced = _coerce_innovus_param_value(value, spec.sample_values)
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


def _get_run_log(run_id: int, lines: int = 50) -> dict[str, Any]:
    """Read the log file from a run and return the last N lines."""
    with get_db() as db:
        row = db.execute(
            text(
                "SELECT r.log_path, r.stage, r.status, d.name AS design_name "
                "FROM runs r JOIN designs d ON d.id = r.design_id WHERE r.id = :rid"
            ),
            {"rid": run_id},
        ).mappings().first()

    if not row:
        return {"error": f"Run {run_id} not found"}

    log_path = row["log_path"]
    if not log_path:
        return {"error": f"No log_path for run {run_id}"}

    log_file = Path(log_path)
    if not log_file.is_file():
        return {"error": f"Log file not found: {log_path}"}

    try:
        all_lines = log_file.read_text().splitlines()
        last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {
            "run_id": run_id,
            "stage": row["stage"],
            "status": row["status"],
            "design_name": row["design_name"],
            "log_path": str(log_path),
            "log_content": "\n".join(last_lines),
        }
    except Exception as e:
        return {"error": f"Failed to read log: {e}"}


def _add_placement_blockage(
    run_id: int,
    blockages: list[dict[str, Any]],
    workdir: str | None = None,
    stage: str = "place",
) -> dict[str, Any]:
    """Apply placement blockages to an Innovus run context and persist metadata."""
    with get_db() as db:
        run_row = db.execute(
            text(
                """
                SELECT r.id AS run_id, r.params, r.stage, b.name AS backend, d.name AS design_name
                FROM runs r
                JOIN designs d ON d.id = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE r.id = :rid
                """
            ),
            {"rid": run_id},
        ).mappings().first()

        if not run_row:
            return {"error": f"Run {run_id} not found"}

        backend_name = str(run_row["backend"]).lower()
        if backend_name != "innovus":
            return {"error": f"add_placement_blockage supports only innovus backend, got '{backend_name}'"}

        be = get_backend(backend_name)
        if not hasattr(be, "add_blockage_to_design_state"):
            return {"error": "Selected backend does not support placement blockage injection"}

        result = be.add_blockage_to_design_state(  # type: ignore[attr-defined]
            design_name=str(run_row["design_name"]),
            blockage_specs=blockages,
            workdir=workdir,
            stage=stage,
        )

        existing_params = run_row["params"] if isinstance(run_row["params"], dict) else {}
        if isinstance(run_row["params"], str):
            try:
                existing_params = json.loads(run_row["params"])
            except json.JSONDecodeError:
                existing_params = {}
        blockage_history = list(existing_params.get("placement_blockages", []))
        blockage_history.extend(blockages)
        updated_params = dict(existing_params)
        updated_params["placement_blockages"] = blockage_history
        db.execute(
            text("UPDATE runs SET params = :params WHERE id = :rid"),
            {"rid": run_id, "params": json.dumps(updated_params)},
        )

    return {
        "run_id": run_id,
        "status": "success",
        "backend": "innovus",
        "applied_blockages": len(blockages),
        "blockages": blockages,
        "details": result,
    }


def _suggest_params(run_id: int, target_spec: str) -> dict[str, Any]:
    """LLM-backed parameter suggestions with heuristic fallback."""
    # ── Gather current run metrics ────────────────────────────────────────────
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

        # Worst timing paths (up to 5) to give LLM concrete path info
        path_rows = db.execute(
            text(
                "SELECT startpoint, endpoint, path_group, slack_ns "
                "FROM timing_paths WHERE run_id = :rid "
                "ORDER BY slack_ns ASC LIMIT 5"
            ),
            {"rid": run_id},
        ).mappings().fetchall()

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
            worst_paths=[dict(p) for p in path_rows],
        )
        return {**suggestions, "run_id": run_id, "target_spec": target_spec, "source": "llm"}
    except Exception:
        logger.warning("LLM suggest_params failed; falling back to heuristics", exc_info=True)

    # ── Heuristic fallback ────────────────────────────────────────────────────
    suggestions_h: dict[str, Any] = {}
    reasoning: list[str] = []
    backend_name = (run_row.get("backend") if run_row else "") or ""
    stage_name = (run_row.get("stage") if run_row else "") or ""

    if backend_name.lower() == "innovus":
        objective = _infer_objective_from_target_spec(target_spec, dict(ts_row) if ts_row else {})
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
                reasoning.append(f"Current WNS={wns:.3f}ns drives stage-specific tuning selection.")
            if hold_vio:
                reasoning.append(f"Detected hold violations={hold_vio}; CTS/post-CTS skew knobs are prioritised.")
            if fep:
                reasoning.append(f"Detected failing endpoints={fep}; timing and congestion knobs are prioritised.")

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

        # Resolve CLOCK_PERIOD from current run params if available
        current_params: dict[str, Any] = {}
        if run_row and run_row.get("params"):
            p = run_row["params"]
            current_params = p if isinstance(p, dict) else {}

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
            reasoning.append(f"WNS={wns:.3f}ns; tightening TNS endpoint coverage to 20%.")

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


def _llm_suggest_params(
    run_id: int,
    target_spec: str,
    ts_row: dict,
    run_row: dict,
    us_row: dict,
    history: list[dict],
    worst_paths: list[dict] | None = None,
) -> dict[str, Any]:
    """Call the MiniMax LLM to produce parameter suggestions.

    Raises an exception if the LLM call fails so the caller can fall back.
    The prompt explicitly instructs the LLM to return **concrete numeric
    values** only – never relative adjustments like "increase by X".
    """
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
        # Extended timing metrics
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

    # Trace the LLM call if enabled
    if is_tracing_enabled():
        raw_response = trace_chat(
            messages=payload["messages"],
            response=raw_response,
            model=model,
        )

    data = raw_response
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


def _bbox_from_wkt(geom_wkt: str) -> tuple[float, float, float, float] | None:
    points = re.findall(
        r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
        geom_wkt,
    )
    if len(points) < 4:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _heuristic_decide_blockages(
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
) -> list[dict[str, Any]]:
    selected = sorted(
        hotspots,
        key=lambda h: float(h.get("overflow", 0) or 0),
        reverse=True,
    )[:max_blockages]

    blockages: list[dict[str, Any]] = []
    for idx, hs in enumerate(selected, start=1):
        geom_wkt = hs.get("geom_wkt")
        bbox = _bbox_from_wkt(geom_wkt) if isinstance(geom_wkt, str) else None
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


def _llm_decide_blockages(
    *,
    run_id: int,
    congestion_summary: dict[str, Any],
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
) -> list[dict[str, Any]]:
    """Use LLM to decide blockage bounding boxes; fallback to heuristics."""
    if not hotspots:
        return []

    summary_json = json.dumps(congestion_summary, ensure_ascii=False)
    hotspot_sample = hotspots[:12]
    hotspot_json = json.dumps(hotspot_sample, ensure_ascii=False)

    system_prompt = (
        "You are an expert Innovus placement optimization engineer. "
        "Return ONLY JSON: {\"blockages\": [...]}.\n"
        "Each blockage item must include x1,y1,x2,y2,type,reason. "
        "Allowed type values: soft, hard, partial. "
        "Use no more than max_blockages items and prioritize highest overflow hotspots."
    )
    user_prompt = (
        f"run_id={run_id}\n"
        f"max_blockages={max_blockages}\n"
        f"congestion_summary={summary_json}\n"
        f"hotspots={hotspot_json}\n"
        "Output strict JSON only."
    )

    api_key = settings.minimax_api_key
    if not api_key:
        return _heuristic_decide_blockages(hotspots, max_blockages=max_blockages)

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
            return _heuristic_decide_blockages(hotspots, max_blockages=max_blockages)
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

    return _heuristic_decide_blockages(hotspots, max_blockages=max_blockages)


def _tune_congestion_with_blockage(
    backend: str,
    design_name: str,
    design_config: str,
    pdk: str,
    congestion_threshold_pct: float = 2.0,
    max_iterations: int = 5,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Iteratively tune place congestion by adding placement blockages."""
    history: list[dict[str, Any]] = []

    for iteration in range(1, max_iterations + 1):
        run_result = _run_eda_stage(
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

        summary = _query_congestion_summary(run_id)
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

        hotspots = _query_congestion(run_id)
        iter_row["hotspot_count"] = len(hotspots)
        if not hotspots:
            iter_row["converged"] = False
            iter_row["error"] = "No congestion hotspots found for blockage synthesis"
            history.append(iter_row)
            break

        blockages = _llm_decide_blockages(
            run_id=run_id,
            congestion_summary=summary,
            hotspots=hotspots,
        )
        if not blockages:
            iter_row["converged"] = False
            iter_row["error"] = "No valid blockage candidates produced"
            history.append(iter_row)
            break

        apply_result = _add_placement_blockage(
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


def _tune_ppa(
    backend: str,
    stage: str,
    design_name: str,
    design_config: str,
    pdk: str,
    target_spec: str,
    max_iterations: int = 5,
) -> dict[str, Any]:
    """Autonomous PPA tuning loop with hill-climbing direction memory.

    For each iteration:
    1. Run the EDA stage with current parameters.
    2. Query timing metrics from the DB.
    3. Check whether the target spec is satisfied.
    4. If WNS regressed vs the previous best, note this so the LLM can pick
       a different direction.
    5. Call ``suggest_params`` to get the next set of parameters.
    6. Repeat until the target is met or ``max_iterations`` is exhausted.

    Only concrete numeric parameter values (int / float / numeric-string)
    are passed to the EDA tool; advisory strings are discarded to prevent
    silently re-running with unchanged parameters.
    """
    history: list[dict[str, Any]] = []
    current_params: dict[str, Any] = {}
    best_wns: float | None = None

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
            "improved": False,
        }

        if status != "success" or run_db_id is None:
            iteration_record["error"] = run_result.get("error")
            history.append(iteration_record)
            break

        # Step 2 – query timing
        timing = _query_timing(design_name, stage=stage, run_id=run_db_id, limit=1)
        summary = timing.get("summary", [])
        current_wns: float | None = None
        if summary:
            current_wns = summary[0].get("wns_ns")
            iteration_record["wns_ns"] = current_wns
            iteration_record["tns_ns"] = summary[0].get("tns_ns")
            iteration_record["failing_endpoints"] = summary[0].get("failing_endpoints")

        # Hill-climbing: track whether WNS improved
        if current_wns is not None:
            if best_wns is None or current_wns > best_wns:
                best_wns = current_wns
                iteration_record["improved"] = True
            else:
                iteration_record["improved"] = False

        # Step 3 – check target
        congestion_summary = _query_congestion_summary(run_db_id)
        target_met = _check_ppa_target(
            timing,
            target_spec,
            congestion_summary=congestion_summary,
        )
        iteration_record["target_met"] = target_met
        iteration_record["congestion_summary"] = congestion_summary
        history.append(iteration_record)

        if target_met:
            logger.info("tune_ppa: target met at iteration %d", iteration)
            break

        if iteration < max_iterations:
            # Annotate target_spec with regression info so LLM picks a new direction
            augmented_spec = target_spec
            if not iteration_record["improved"] and iteration > 1:
                augmented_spec = (
                    f"{target_spec} "
                    f"[last params did NOT improve WNS; try a different direction]"
                )

            # Step 4 – get next params
            suggestion = _suggest_params(run_db_id, augmented_spec)
            raw_params = suggestion.get("suggested_params", {})

            filtered = _filter_suggested_params(raw_params, backend=backend, stage=stage)

            if not filtered and raw_params:
                logger.warning(
                    "tune_ppa: all suggested params were dropped after validation; "
                    "re-running with same params (iteration %d)",
                    iteration,
                )
            current_params = filtered

    return {
        "iterations_run": len(history),
        "target_spec": target_spec,
        "target_met": any(r.get("target_met") for r in history),
        "best_wns_ns": best_wns,
        "history": history,
    }


def _check_ppa_target(
    timing: dict[str, Any],
    target_spec: str,
    congestion_summary: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a natural-language PPA target against timing data.

    Supports multi-metric patterns (case-insensitive):
      - WNS >= -0.1
      - TNS <= -5
      - fmax >= 500
      - fep == 0  /  failing_endpoints == 0
      - setup_violations == 0
      - hold_violations == 0
      - overflow_h_pct <= 2.0 / overflow_v_pct <= 2.0 / overflow <= 2.0

    Multiple conditions joined by 'and' are all required to be true.
    Returns True if all parsed conditions are satisfied, or if no
    recognisable condition is found and there are 0 failing endpoints.
    """
    import re

    summary = timing.get("summary", [])
    if not summary:
        return False

    latest = summary[0]
    spec_lower = target_spec.lower()

    # Map metric aliases → data key in the timing summary dict
    _METRIC_MAP = {
        "wns": "wns_ns",
        "tns": "tns_ns",
        "fmax": "fmax_mhz",
        "fep": "failing_endpoints",
        "failing_endpoints": "failing_endpoints",
        "failing endpoints": "failing_endpoints",
        "setup_violations": "setup_violations",
        "hold_violations": "hold_violations",
    }
    _CONGESTION_METRIC_MAP = {
        "overflow_h_pct": "overflow_h_pct",
        "overflow_v_pct": "overflow_v_pct",
    }

    # Pattern: <metric> <op> <value>
    _TIMING_COND_RE = re.compile(
        r"(wns|tns|fmax|fep|failing[_ ]endpoints|setup_violations|hold_violations)"
        r"\s*(>=|<=|>|<|==)\s*(-?[\d.]+)",
        re.IGNORECASE,
    )
    _CONGESTION_COND_RE = re.compile(
        r"(overflow_h_pct|overflow_v_pct|overflow_pct|overflow)\s*(>=|<=|>|<|==)\s*(-?[\d.]+)%?",
        re.IGNORECASE,
    )

    timing_conditions = _TIMING_COND_RE.findall(spec_lower)
    congestion_conditions = _CONGESTION_COND_RE.findall(spec_lower)
    if not timing_conditions and not congestion_conditions:
        # No parseable spec → satisfied when FEP == 0
        return (latest.get("failing_endpoints") or 0) == 0

    def _apply(op: str, actual: float, threshold: float) -> bool:
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
        data_key = _METRIC_MAP.get(metric_alias.replace(" ", "_"))
        if data_key is None:
            continue
        actual = latest.get(data_key)
        if actual is None:
            return False
        if not _apply(op, float(actual), float(raw_threshold)):
            return False

    if congestion_conditions:
        summary = congestion_summary or {}
        if not summary:
            return False
        for metric_alias, op, raw_threshold in congestion_conditions:
            alias = metric_alias.lower()
            if alias in {"overflow", "overflow_pct"}:
                overflow_h = float(summary.get("overflow_h_pct", 0.0) or 0.0)
                overflow_v = float(summary.get("overflow_v_pct", 0.0) or 0.0)
                actual = max(overflow_h, overflow_v)
            else:
                data_key = _CONGESTION_METRIC_MAP.get(alias)
                if data_key is None:
                    continue
                actual = summary.get(data_key)
            if actual is None:
                return False
            if not _apply(op, float(actual), float(raw_threshold)):
                return False

    return True


# ── Multi-stage tuning ────────────────────────────────────────────────────────

# Ordered ORFS stages used for multi-stage traversal
_ORFS_STAGE_ORDER: list[str] = ["synth", "floorplan", "place", "cts", "route", "finish"]


def _pick_bottleneck_stage(
    timing: dict[str, Any],
    run_id: int | None = None,
    congestion_threshold_pct: float = 2.0,
) -> str:
    """Choose which stage to re-run based on violation profile.

    Decision rules (checked in priority order):
    - Hold violations present → re-run CTS (clock skew / hold buffer insertion)
    - DRC violations or route congestion → re-run route
    - High congestion → re-run place
    - Setup violations / negative WNS → re-run CTS (timing closure)
    - Otherwise → re-run place (general timing improvement)
    """
    summary = timing.get("summary", [{}])[0] if timing.get("summary") else {}
    if run_id is not None:
        try:
            congestion = _query_congestion_summary(run_id)
            overflow_h_pct = float(congestion.get("overflow_h_pct", 0.0) or 0.0)
            overflow_v_pct = float(congestion.get("overflow_v_pct", 0.0) or 0.0)
            if max(overflow_h_pct, overflow_v_pct) > congestion_threshold_pct:
                return "place"
        except Exception:
            logger.debug("Failed to query congestion summary for run_id=%s", run_id, exc_info=True)

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


def _tune_ppa_multistage(
    backend: str,
    design_name: str,
    design_config: str,
    pdk: str,
    target_spec: str,
    start_stage: str = "place",
    max_iterations: int = 5,
) -> dict[str, Any]:
    """Multi-stage autonomous PPA tuning loop.

    Each iteration:
    1. Run all stages from ``rerun_from`` through ``finish``.
    2. Collect PPA metrics (timing, congestion, utilization).
    3. Check whether the target is met.
    4. Identify the bottleneck stage from the violation profile.
    5. Suggest parameters for that stage via ``suggest_params``.
    6. Re-run from the bottleneck stage in the next iteration.
    """
    history: list[dict[str, Any]] = []
    stage_params: dict[str, dict[str, Any]] = {}  # per-stage param overrides
    rerun_from: str = start_stage
    best_wns: float | None = None

    # Determine the terminal stage index
    try:
        start_idx = _ORFS_STAGE_ORDER.index(start_stage)
    except ValueError:
        start_idx = 0

    for iteration in range(1, max_iterations + 1):
        logger.info(
            "tune_ppa_multistage iteration %d/%d  rerun_from=%s  stage_params=%s",
            iteration, max_iterations, rerun_from, stage_params,
        )

        try:
            rerun_idx = _ORFS_STAGE_ORDER.index(rerun_from)
        except ValueError:
            rerun_idx = start_idx

        stages_to_run = _ORFS_STAGE_ORDER[rerun_idx:]

        iteration_record: dict[str, Any] = {
            "iteration": iteration,
            "rerun_from": rerun_from,
            "stages_run": [],
            "target_met": False,
            "improved": False,
        }

        last_run_id: int | None = None
        last_timing: dict[str, Any] = {}

        for stage in stages_to_run:
            params = stage_params.get(stage, {})
            run_result = _run_eda_stage(
                backend=backend,
                stage=stage,
                design_name=design_name,
                design_config=design_config,
                pdk=pdk,
                params=params,
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
                break

            last_run_id = run_result.get("run_id")
            # Query timing after each stage for progress tracking
            timing = _query_timing(design_name, stage=stage, run_id=last_run_id, limit=1)
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

        # Use the finish-stage timing for target evaluation
        if not last_timing and last_run_id:
            last_timing = _query_timing(design_name, run_id=last_run_id, limit=1)

        # Hill-climbing direction memory
        fin_summary = last_timing.get("summary", [{}])[0] if last_timing.get("summary") else {}
        current_wns = fin_summary.get("wns_ns")
        if current_wns is not None:
            iteration_record["wns_ns"] = current_wns
            if best_wns is None or current_wns > best_wns:
                best_wns = current_wns
                iteration_record["improved"] = True

        # Check target
        final_congestion_summary = _query_congestion_summary(last_run_id) if last_run_id else {}
        target_met = _check_ppa_target(
            last_timing,
            target_spec,
            congestion_summary=final_congestion_summary,
        )
        iteration_record["target_met"] = target_met
        iteration_record["congestion_summary"] = final_congestion_summary
        history.append(iteration_record)

        if target_met:
            logger.info("tune_ppa_multistage: target met at iteration %d", iteration)
            break

        if iteration < max_iterations and last_run_id is not None:
            # Pick bottleneck stage and suggest params for it
            bottleneck = _pick_bottleneck_stage(last_timing, run_id=last_run_id)

            augmented_spec = target_spec
            if not iteration_record["improved"] and iteration > 1:
                augmented_spec = (
                    f"{target_spec} "
                    f"[last params did NOT improve WNS; try a different direction]"
                )

            suggestion = _suggest_params(last_run_id, augmented_spec)
            raw_params = suggestion.get("suggested_params", {})

            filtered = _filter_suggested_params(raw_params, backend=backend, stage=bottleneck)

            if filtered:
                stage_params[bottleneck] = filtered
                rerun_from = bottleneck
                iteration_record["next_bottleneck_stage"] = bottleneck
                iteration_record["next_params"] = filtered
            else:
                # No actionable suggestions; retry from the same stage
                rerun_from = bottleneck

    return {
        "iterations_run": len(history),
        "target_spec": target_spec,
        "target_met": any(r.get("target_met") for r in history),
        "best_wns_ns": best_wns,
        "history": history,
    }


def _save_case_tool(
    symptoms: str,
    root_cause: str,
    design_name: str = "",
    pdk: str = "",
    actions: list[str] | None = None,
    result_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a resolved debugging case to the case_memory table."""
    from eda_agent.agent.memory import save_case

    case_id = save_case(
        design_name=design_name,
        symptoms=symptoms,
        root_cause=root_cause,
        pdk=pdk,
        actions=actions,
        result_metrics=result_metrics,
    )
    return {"status": "saved", "case_id": case_id}


def _infer_root_cause_tool(run_id: int, symptoms: str = "") -> dict[str, Any]:
    """Invoke the rule-based inference engine and return ranked hypotheses."""
    from eda_agent.agent.inference.engine import infer

    return infer(run_id=run_id, symptoms=symptoms)


def _confirm_root_cause_tool(
    inference_id: int, confirmed_cause_id: str
) -> dict[str, Any]:
    """Confirm the engineer-approved root cause and save to case memory."""
    from eda_agent.agent.inference.engine import confirm

    return confirm(inference_id=inference_id, confirmed_cause_id=confirmed_cause_id)


# ── Dispatch table ────────────────────────────────────────────────────────────

_TOOL_DISPATCH = {
    "run_eda_stage": _run_eda_stage,
    "run_eda_flow": _run_eda_flow,
    "get_run_log": _get_run_log,
    "query_timing": _query_timing,
    "query_congestion": _query_congestion,
    "query_congestion_summary": _query_congestion_summary,
    "query_utilization": _query_utilization,
    "query_power": _query_power,
    "compare_runs": _compare_runs,
    "suggest_params": _suggest_params,
    "tune_ppa": _tune_ppa,
    "tune_ppa_multistage": _tune_ppa_multistage,
    "add_placement_blockage": _add_placement_blockage,
    "tune_congestion_with_blockage": _tune_congestion_with_blockage,
    # Async job queue tools
    "submit_job": _submit_job,
    "job_status": _job_status,
    "job_logs": _job_logs,
    "cancel_job": _cancel_job,
    "save_case": _save_case_tool,
    "infer_root_cause": _infer_root_cause_tool,
    "confirm_root_cause": _confirm_root_cause_tool,
}


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name with *arguments* and return a JSON string.

    All calls pass through the guardrail layer first.  Blocked calls return a
    structured ``{"blocked": true, ...}`` JSON response without invoking the
    underlying function.  WARN-level calls execute normally but include a
    ``_warnings`` list in the result.
    """
    from eda_agent.agent.guardrails import RiskLevel, check

    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    # Strip internal guardrail flag before forwarding to implementation
    args = {k: v for k, v in arguments.items() if k != "_guardrail_confirmed"}

    # Guardrail check (uses original arguments so confirmed flag is visible)
    gr = check(name, arguments)
    if gr.is_blocked:
        return json.dumps(gr.blocked_response(name, args))

    try:
        result = fn(**args)
        # Attach warnings to result when present
        if gr.level == RiskLevel.WARN and gr.warnings:
            if isinstance(result, dict):
                result["_warnings"] = gr.warnings
            else:
                # Wrap non-dict results
                result = {"result": result, "_warnings": gr.warnings}
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


def _upsert_artifacts(run_id: int, reports: list[Any]) -> None:
    """Persist collected report files into artifacts table (best effort)."""
    with get_db() as db:
        for rpt in reports:
            path = Path(str(rpt.path))
            file_size = path.stat().st_size if path.exists() else None
            db.execute(
                text(
                    """
                    INSERT INTO artifacts (run_id, file_path, artifact_type, file_size_bytes)
                    VALUES (:run_id, :file_path, :artifact_type, :file_size_bytes)
                    """
                ),
                {
                    "run_id": run_id,
                    "file_path": str(path),
                    "artifact_type": str(getattr(rpt, "report_type", "generic")),
                    "file_size_bytes": file_size,
                },
            )


def _ingest_records(records: list[dict], run_id: int, stage: str) -> None:
    """Fan out parsed records into the appropriate DB tables."""
    with get_db() as db:
        for rec in records:
            kind = rec.get("kind")
            if kind == "summary" and "wns_ns" in rec:
                db.execute(
                    text(
                        "INSERT INTO timing_summary "
                        "(run_id, view, wns_ns, tns_ns, failing_endpoints, "
                        " fmax_mhz, clock_skew_ns, max_slew_violations, "
                        " max_fanout_violations, max_cap_violations, "
                        " setup_violations, hold_violations, "
                        " critical_path_delay_ns, slack_cpd_ratio_pct) "
                        "VALUES (:run_id, :view, :wns, :tns, :fep, "
                        " :fmax, :skew, :slew_vio, :fanout_vio, :cap_vio, "
                        " :setup_vio, :hold_vio, :cpd, :ratio)"
                    ),
                    {
                        "run_id": run_id,
                        "view": rec.get("view", "default"),
                        "wns": rec.get("wns_ns"),
                        "tns": rec.get("tns_ns"),
                        "fep": rec.get("failing_endpoints"),
                        "fmax": rec.get("fmax_mhz"),
                        "skew": rec.get("clock_skew_ns"),
                        "slew_vio": rec.get("max_slew_violations"),
                        "fanout_vio": rec.get("max_fanout_violations"),
                        "cap_vio": rec.get("max_cap_violations"),
                        "setup_vio": rec.get("setup_violations"),
                        "hold_vio": rec.get("hold_violations"),
                        "cpd": rec.get("critical_path_delay_ns"),
                        "ratio": rec.get("slack_cpd_ratio_pct"),
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
                        "(run_id, geom_wkt, overflow) "
                        "VALUES (:run_id, :wkt, :overflow)"
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
                        "(run_id, geom_wkt, overflow, layer) "
                        "VALUES (:run_id, :wkt, :overflow, :layer)"
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
