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
query_congestion    – spatial congestion query via PostGIS
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
import subprocess
from time import perf_counter
from typing import Any

from sqlalchemy import text

from eda_agent.agent.custom_tools import (
    CustomToolConfigError,
    load_custom_tools,
    load_custom_tools_from_entry_points,
)
from eda_agent.agent.param_mapper import OptimizationObjective
from eda_agent.agent.tool_schemas import TOOL_SCHEMAS as BUILTIN_TOOL_SCHEMAS
from eda_agent.db.repository import EDAQueryRepository
from eda_agent.backends.base import DesignSpec
from eda_agent.config import settings
from eda_agent.db.session import get_db, is_postgresql
from eda_agent.parsers import get_parser

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

# ── Tool implementations ──────────────────────────────────────────────────────


# ── Transaction-safe save helper ─────────────────────────────────────────


def _save_run_and_parse(
    result: Any,
    design: DesignSpec,
    backend: Any = None,
    run_context: dict[str, Any] | None = None,
) -> int:
    """Atomically upsert a run and ingest its parsed reports.

    Unlike separate ``_upsert_run`` + ``_ingest_records`` calls (each in
    their own transaction), this wraps both operations in **one** transaction
    so a mid-way crash never produces an orphaned run record.

    Parse errors are caught and logged but do **not** roll back the run:
    the run is still useful even when some report types fail to parse.
    """
    with get_db() as db:
        run_db_id = _upsert_run(result, design, db=db, run_context=run_context)

        if result.status.value == "success" and backend is not None:
            reports = backend.collect_reports(result)
            try:
                _upsert_artifacts_with_db(run_db_id, reports, db)
            except Exception:
                logger.debug(
                    "Failed to upsert artifacts for run %s", run_db_id, exc_info=True
                )
            for rpt in reports:
                try:
                    parser = get_parser(rpt.report_type)
                    records = parser.parse_file(rpt.path)
                    _ingest_records(records, run_db_id, rpt.stage, db=db)
                except Exception as e:
                    # Best-effort: don't fail the run for parse errors
                    logger.debug("Failed to parse %s: %s", rpt.path, e)

        # Transaction commits here (get_db context manager exit)
    return run_db_id


def _create_flow_session(
    design: DesignSpec,
    objective: str = "pnr",
    notes: str = "",
) -> int:
    """Create a flow session row and return its id.

    A session groups one multi-stage flow execution (baseline or variant) so we
    can detect completion based on the *last stage in that session*.
    """
    from eda_agent.agent.tool_impl_flow_session import create_flow_session_impl

    return create_flow_session_impl(
        design,
        objective=objective,
        notes=notes,
        get_db_fn=get_db,
    )


def _update_flow_session_status(
    session_id: int,
    status: str,
    baseline_run_id: int | None = None,
) -> None:
    """Update flow session lifecycle state (active/completed/failed)."""
    from eda_agent.agent.tool_impl_flow_session import update_flow_session_status_impl

    update_flow_session_status_impl(
        session_id,
        status,
        baseline_run_id=baseline_run_id,
        get_db_fn=get_db,
    )


def _record_stage_outcome(
    run_id: int,
    stage_name: str,
    result: Any,
    recommendation: str = "",
    approval_status: str = "pending",
    root_cause_inference_id: int | None = None,
) -> None:
    """Persist per-stage execution snapshot for reproducibility."""
    output_metrics = {
        "status": result.status.value,
        "error": result.error_message,
        "run_uuid": result.run_id,
    }
    artifact_refs: list[str] = []
    if result.log_path:
        artifact_refs.append(str(result.log_path))

    _jc = "::jsonb" if is_postgresql() else ""
    with get_db() as db:
        db.execute(
            text(
                f"""
                INSERT INTO stage_outcomes
                    (run_id, stage_name, status, started_at, finished_at,
                     input_params_snapshot, output_metrics_snapshot, artifact_refs,
                     root_cause_inference_id, recommendation, approval_status)
                VALUES
                    (:run_id, :stage_name, :status, :started_at, :finished_at,
                     :input_params_snapshot{_jc}, :output_metrics_snapshot{_jc},
                     :artifact_refs{_jc}, :root_cause_inference_id,
                     :recommendation, :approval_status)
                """
            ),
            {
                "run_id": run_id,
                "stage_name": stage_name,
                "status": result.status.value,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "input_params_snapshot": json.dumps(result.params or {}),
                "output_metrics_snapshot": json.dumps(output_metrics),
                "artifact_refs": json.dumps(artifact_refs),
                "root_cause_inference_id": root_cause_inference_id,
                "recommendation": recommendation,
                "approval_status": approval_status,
            },
        )


def _decision_reason_from_suggestion(suggestion: dict[str, Any], prefix: str = "") -> str:
    """Build a compact textual rationale for decision_trace from suggestion output."""
    from eda_agent.agent.tool_impl_trace import decision_reason_from_suggestion_impl

    return decision_reason_from_suggestion_impl(suggestion, prefix=prefix)


def _decision_reason_structured_from_suggestion(
    suggestion: dict[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """Build a structured rationale payload for decision_trace."""
    from eda_agent.agent.tool_impl_trace import (
        decision_reason_structured_from_suggestion_impl,
    )

    return decision_reason_structured_from_suggestion_impl(suggestion, prefix=prefix)


def _record_decision_trace(
    session_id: int,
    source_run_id: int,
    target_run_id: int,
    *,
    llm_reason: str = "",
    llm_reason_structured: dict[str, Any] | None = None,
    inference_id: int | None = None,
    case_id: int | None = None,
    rule_id: str | None = None,
    human_approved: bool = False,
) -> None:
    """Persist lineage from diagnosis/suggestion to the next rerun."""
    from eda_agent.agent.tool_impl_trace import record_decision_trace_impl

    record_decision_trace_impl(
        session_id,
        source_run_id,
        target_run_id,
        llm_reason=llm_reason,
        llm_reason_structured=llm_reason_structured,
        inference_id=inference_id,
        case_id=case_id,
        rule_id=rule_id,
        human_approved=human_approved,
        get_db_fn=get_db,
    )


def _set_flow_session_inference_context(
    session_id: int,
    *,
    inference_id: int | None = None,
    case_id: int | None = None,
    rule_id: str | None = None,
) -> None:
    """Persist latest inference/case/rule context on a flow session."""
    from eda_agent.agent.tool_impl_trace import set_flow_session_inference_context_impl

    set_flow_session_inference_context_impl(
        session_id,
        inference_id=inference_id,
        case_id=case_id,
        rule_id=rule_id,
        get_db_fn=get_db,
    )


def _set_flow_session_context_from_run(
    run_id: int,
    *,
    inference_id: int | None = None,
    case_id: int | None = None,
    rule_id: str | None = None,
) -> None:
    """Resolve session_id by run_id and update session inference context."""
    from eda_agent.agent.tool_impl_trace import set_flow_session_context_from_run_impl

    set_flow_session_context_from_run_impl(
        run_id,
        inference_id=inference_id,
        case_id=case_id,
        rule_id=rule_id,
        get_db_fn=get_db,
        set_flow_session_inference_context_fn=_set_flow_session_inference_context,
    )


def _latest_inference_context_for_run(run_id: int) -> dict[str, Any]:
    """Best-effort lookup for inference/case context linked to *run_id*.

    Returns a dict with keys: inference_id, case_id, rule_id.  Missing values
    are returned as None so callers can pass through directly.
    """
    from eda_agent.agent.tool_impl_trace import latest_inference_context_for_run_impl

    return latest_inference_context_for_run_impl(run_id, get_db_fn=get_db)


def _run_eda_stage(
    backend: str,
    stage: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    params: dict[str, Any] | None = None,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_run_stage import run_eda_stage_impl

    return run_eda_stage_impl(
        backend=backend,
        stage=stage,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
        params=params,
        run_context=run_context,
        resolve_identity_fn=_resolve_backend_design_identity,
        save_run_and_parse_fn=_save_run_and_parse,
        record_stage_outcome_fn=_record_stage_outcome,
    )


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
    from eda_agent.agent.tool_impl_run_stage import run_eda_flow_sync_impl

    return run_eda_flow_sync_impl(
        backend=backend,
        stage_start=stage_start,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        stage_end=stage_end,
        params=params,
        clean=clean,
        create_flow_session_fn=_create_flow_session,
        save_run_and_parse_fn=_save_run_and_parse,
        record_decision_trace_fn=_record_decision_trace,
        record_stage_outcome_fn=_record_stage_outcome,
        update_flow_session_status_fn=_update_flow_session_status,
    )


def _run_eda_flow(
    backend: str,
    stage_start: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    stage_end: str | None = None,
    params: dict[str, Any] | None = None,
    clean: bool = False,
) -> dict[str, Any]:
    """Submit a flow job asynchronously to keep CLI interactive.

    NOTE: Synchronous flow execution is implemented by ``_run_eda_flow_sync``
    and is used by the background worker.
    """
    from eda_agent.agent.tool_impl_job import run_eda_flow_async_impl

    return run_eda_flow_async_impl(
        backend=backend,
        stage_start=stage_start,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
        stage_end=stage_end,
        params=params,
        clean=clean,
        resolve_identity_fn=_resolve_backend_design_identity,
        submit_job_fn=_submit_job,
    )


# ── Async job queue tools ───────────────────────────────────────────────────


def _submit_job(
    backend: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    stage: str | None = None,
    params: dict[str, Any] | None = None,
    stage_start: str | None = None,
    stage_end: str | None = None,
    run_mode: str = "stage",
) -> dict[str, Any]:
    """Submit an async job to the queue (stage or flow mode)."""
    from eda_agent.agent.tool_impl_job import submit_job_impl

    return submit_job_impl(
        backend=backend,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
        stage=stage,
        params=params,
        stage_start=stage_start,
        stage_end=stage_end,
        run_mode=run_mode,
        resolve_identity_fn=_resolve_backend_design_identity,
        ensure_worker_running_fn=_ensure_worker_running,
        on_worker_start_error=(
            lambda _exc: logger.warning(
                "Failed to auto-start worker after job submission",
                exc_info=True,
            )
        ),
    )


def _run_multi_agent_cycle_tool(
    objective: str,
    session_id: int | None = None,
    run_id: int | None = None,
    constraints: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    agents: list[str] | None = None,
    execute_experiment: bool = False,
    experiment_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one multi-agent cycle and optionally run an experiment stage."""
    from eda_agent.agent.tool_impl_multi_agent import run_multi_agent_cycle_tool_impl

    return run_multi_agent_cycle_tool_impl(
        objective=objective,
        session_id=session_id,
        run_id=run_id,
        constraints=constraints,
        inputs=inputs,
        agents=agents,
        execute_experiment=execute_experiment,
        experiment_request=experiment_request,
        run_eda_stage_fn=_run_eda_stage,
        resolve_identity_fn=_resolve_backend_design_identity,
        record_decision_trace_fn=_record_decision_trace,
    )


def _resolve_backend_design_identity(
    backend: str,
    design_config: str | None,
    pdk: str | None,
    *,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
) -> tuple[str, str]:
    """Normalize backend-specific design identity fields.

    Historical API fields are ``design_config`` + ``pdk``. For Innovus these
    can be provided more explicitly via aliases:
    - ``innovus_workdir`` -> ``design_config``
    - ``tech_profile`` -> ``pdk``
    """
    backend_l = (backend or "").lower()

    cfg = design_config
    tech = pdk

    if backend_l == "innovus":
        cfg = cfg or innovus_workdir or settings.innovus_remote_workdir
        tech = tech or tech_profile or "tsmc18"

    if not cfg:
        raise ValueError(
            "design_config is required. For innovus, you can set "
            "innovus_workdir or INNOVUS_REMOTE_WORKDIR."
        )
    if not tech:
        raise ValueError(
            "pdk is required. For innovus, you can set tech_profile "
            "(default tsmc18)."
        )

    return cfg, tech


def _job_status(job_id: str) -> dict[str, Any]:
    """Check async job status."""
    from eda_agent.agent.tool_impl_job import job_status_impl

    return job_status_impl(job_id)


def _job_logs(job_id: str, lines: int = 50) -> dict[str, Any]:
    """Get log file from async job."""
    from eda_agent.agent.tool_impl_job import job_logs_impl

    return job_logs_impl(job_id, lines=lines)


def _cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a pending/pending_async job."""
    from eda_agent.agent.tool_impl_job import cancel_job_impl

    return cancel_job_impl(job_id)


def _query_timing(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_query import query_timing_impl

    return query_timing_impl(
        design_name=design_name,
        stage=stage,
        run_id=run_id,
        limit=limit,
    )


def _query_congestion(
    run_id: int,
    x1: float | None = None,
    y1: float | None = None,
    x2: float | None = None,
    y2: float | None = None,
) -> list[dict[str, Any]]:
    from eda_agent.agent.tool_impl_query import query_congestion_impl

    return query_congestion_impl(run_id=run_id, x1=x1, y1=y1, x2=x2, y2=y2)


def _query_congestion_summary(run_id: int) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_query import query_congestion_summary_impl

    return query_congestion_summary_impl(run_id)


def _compare_runs(run_id_a: int, run_id_b: int) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_query import compare_runs_impl

    return compare_runs_impl(run_id_a, run_id_b)


def _query_flow_sessions(
    design_name: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from eda_agent.agent.tool_impl_query import query_flow_sessions_impl

    return query_flow_sessions_impl(
        design_name=design_name,
        status=status,
        limit=limit,
    )


def _query_session_trace(
    session_id: int,
    stage: str | None = None,
    from_seq: int | None = None,
    to_seq: int | None = None,
    human_approved: bool | None = None,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_query import query_session_trace_impl

    return query_session_trace_impl(
        session_id=session_id,
        stage=stage,
        from_seq=from_seq,
        to_seq=to_seq,
        human_approved=human_approved,
    )


def _infer_objective_from_target_spec(
    target_spec: str,
    timing_summary: dict[str, Any] | None = None,
) -> OptimizationObjective:
    from eda_agent.agent.tool_impl_suggest import infer_objective_from_target_spec_impl

    return infer_objective_from_target_spec_impl(target_spec, timing_summary)


def _coerce_innovus_param_value(raw_value: Any, sample_values: list[Any]) -> Any:
    from eda_agent.agent.tool_impl_suggest import coerce_innovus_param_value_impl

    return coerce_innovus_param_value_impl(raw_value, sample_values)


def _filter_suggested_params(
    raw_params: dict[str, Any],
    backend: str,
    stage: str,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_suggest import filter_suggested_params_impl

    return filter_suggested_params_impl(raw_params, backend, stage)


def _query_utilization(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    from eda_agent.agent.tool_impl_query import query_utilization_impl

    return query_utilization_impl(
        design_name=design_name,
        stage=stage,
        run_id=run_id,
        limit=limit,
    )


def _query_power(
    design_name: str,
    stage: str | None = None,
    run_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    from eda_agent.agent.tool_impl_query import query_power_impl

    return query_power_impl(
        design_name=design_name,
        stage=stage,
        run_id=run_id,
        limit=limit,
    )


def _get_run_log(run_id: int, lines: int = 50) -> dict[str, Any]:
    """Read the log file from a run and return the last N lines."""
    from eda_agent.agent.tool_impl_query import get_run_log_impl

    return get_run_log_impl(run_id, lines=lines)


def _add_placement_blockage(
    run_id: int,
    blockages: list[dict[str, Any]],
    workdir: str | None = None,
    stage: str = "place",
) -> dict[str, Any]:
    """Apply placement blockages to an Innovus run context and persist metadata."""
    from eda_agent.agent.tool_impl_blockage import add_placement_blockage_impl

    return add_placement_blockage_impl(
        run_id,
        blockages,
        workdir=workdir,
        stage=stage,
        get_db_fn=get_db,
    )


def _suggest_params(run_id: int, target_spec: str) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_suggest import suggest_params_impl

    return suggest_params_impl(
        run_id,
        target_spec,
        llm_suggest_params_fn=_llm_suggest_params,
    )


def _llm_suggest_params(
    run_id: int,
    target_spec: str,
    ts_row: dict,
    run_row: dict,
    us_row: dict,
    history: list[dict],
    worst_paths: list[dict] | None = None,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_suggest import llm_suggest_params_impl

    return llm_suggest_params_impl(
        run_id=run_id,
        target_spec=target_spec,
        ts_row=ts_row,
        run_row=run_row,
        us_row=us_row,
        history=history,
        worst_paths=worst_paths,
    )


def _bbox_from_wkt(geom_wkt: str) -> tuple[float, float, float, float] | None:
    from eda_agent.agent.tool_impl_tuning import bbox_from_wkt_impl

    return bbox_from_wkt_impl(geom_wkt)


def _heuristic_decide_blockages(
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
) -> list[dict[str, Any]]:
    from eda_agent.agent.tool_impl_tuning import heuristic_decide_blockages_impl

    return heuristic_decide_blockages_impl(
        hotspots,
        max_blockages=max_blockages,
        bbox_from_wkt_fn=_bbox_from_wkt,
    )


def _llm_decide_blockages(
    *,
    run_id: int,
    congestion_summary: dict[str, Any],
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
) -> list[dict[str, Any]]:
    from eda_agent.agent.tool_impl_tuning import llm_decide_blockages_impl

    return llm_decide_blockages_impl(
        run_id=run_id,
        congestion_summary=congestion_summary,
        hotspots=hotspots,
        max_blockages=max_blockages,
        heuristic_decide_blockages_fn=_heuristic_decide_blockages,
    )


def _tune_congestion_with_blockage(
    backend: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    congestion_threshold_pct: float = 2.0,
    max_iterations: int = 5,
    workdir: str | None = None,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_tuning import tune_congestion_with_blockage_impl

    return tune_congestion_with_blockage_impl(
        backend=backend,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
        congestion_threshold_pct=congestion_threshold_pct,
        max_iterations=max_iterations,
        workdir=workdir,
        resolve_backend_design_identity_fn=_resolve_backend_design_identity,
        run_eda_stage_fn=_run_eda_stage,
        query_congestion_summary_fn=_query_congestion_summary,
        query_congestion_fn=_query_congestion,
        llm_decide_blockages_fn=_llm_decide_blockages,
        add_placement_blockage_fn=_add_placement_blockage,
    )


def _tune_ppa(
    backend: str,
    stage: str,
    design_name: str,
    target_spec: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    max_iterations: int = 5,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_tuning import tune_ppa_impl

    return tune_ppa_impl(
        backend=backend,
        stage=stage,
        design_name=design_name,
        target_spec=target_spec,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
        max_iterations=max_iterations,
        resolve_backend_design_identity_fn=_resolve_backend_design_identity,
        create_flow_session_fn=_create_flow_session,
        run_eda_stage_fn=_run_eda_stage,
        update_flow_session_status_fn=_update_flow_session_status,
        record_decision_trace_fn=_record_decision_trace,
        query_timing_fn=_query_timing,
        query_congestion_summary_fn=_query_congestion_summary,
        check_ppa_target_fn=_check_ppa_target,
        suggest_params_fn=_suggest_params,
        filter_suggested_params_fn=_filter_suggested_params,
        latest_inference_context_for_run_fn=_latest_inference_context_for_run,
        decision_reason_from_suggestion_fn=_decision_reason_from_suggestion,
        decision_reason_structured_from_suggestion_fn=_decision_reason_structured_from_suggestion,
    )


def _check_ppa_target(
    timing: dict[str, Any],
    target_spec: str,
    congestion_summary: dict[str, Any] | None = None,
) -> bool:
    from eda_agent.agent.tool_impl_tuning import check_ppa_target_impl

    return check_ppa_target_impl(
        timing,
        target_spec,
        congestion_summary=congestion_summary,
    )


def _pick_bottleneck_stage(
    timing: dict[str, Any],
    run_id: int | None = None,
    congestion_threshold_pct: float = 2.0,
) -> str:
    from eda_agent.agent.tool_impl_tuning import pick_bottleneck_stage_impl

    return pick_bottleneck_stage_impl(
        timing,
        run_id=run_id,
        congestion_threshold_pct=congestion_threshold_pct,
        query_congestion_summary_fn=_query_congestion_summary,
    )


def _tune_ppa_multistage(
    backend: str,
    design_name: str,
    target_spec: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    start_stage: str = "place",
    max_iterations: int = 5,
) -> dict[str, Any]:
    from eda_agent.agent.tool_impl_tuning import tune_ppa_multistage_impl

    return tune_ppa_multistage_impl(
        backend=backend,
        design_name=design_name,
        target_spec=target_spec,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
        start_stage=start_stage,
        max_iterations=max_iterations,
        resolve_backend_design_identity_fn=_resolve_backend_design_identity,
        create_flow_session_fn=_create_flow_session,
        run_eda_stage_fn=_run_eda_stage,
        update_flow_session_status_fn=_update_flow_session_status,
        record_decision_trace_fn=_record_decision_trace,
        query_timing_fn=_query_timing,
        query_congestion_summary_fn=_query_congestion_summary,
        check_ppa_target_fn=_check_ppa_target,
        pick_bottleneck_stage_fn=_pick_bottleneck_stage,
        suggest_params_fn=_suggest_params,
        filter_suggested_params_fn=_filter_suggested_params,
        latest_inference_context_for_run_fn=_latest_inference_context_for_run,
        decision_reason_from_suggestion_fn=_decision_reason_from_suggestion,
        decision_reason_structured_from_suggestion_fn=_decision_reason_structured_from_suggestion,
    )


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


def _optimize_with_inference_tool(
    run_id: int,
    target_spec: str,
    backend: str,
    stage: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    max_iterations: int = 5,
) -> dict[str, Any]:
    """Run inference-guided optimisation loop as an LLM tool."""
    from eda_agent.agent.optimization_loop import optimize_with_inference

    design_config, pdk = _resolve_backend_design_identity(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    return optimize_with_inference(
        run_id=run_id,
        target_spec=target_spec,
        backend=backend,
        stage=stage,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
        max_iterations=max_iterations,
    )


def _infer_root_cause_tool(run_id: int, symptoms: str = "") -> dict[str, Any]:
    """Invoke the rule-based inference engine and return ranked hypotheses."""
    from eda_agent.agent.inference.engine import infer

    result = infer(run_id=run_id, symptoms=symptoms)
    inference_id = result.get("inference_id")
    rule_id = None
    hypotheses = result.get("hypotheses") or []
    if isinstance(hypotheses, list) and hypotheses:
        top = hypotheses[0]
        if isinstance(top, dict):
            rule_id = top.get("cause_id")
    if isinstance(inference_id, int) and inference_id > 0:
        try:
            _set_flow_session_context_from_run(
                run_id,
                inference_id=inference_id,
                rule_id=rule_id,
            )
        except Exception:
            logger.warning("Failed to persist flow-session inference context", exc_info=True)
    return result


def _confirm_root_cause_tool(
    inference_id: int, confirmed_cause_id: str
) -> dict[str, Any]:
    """Confirm the engineer-approved root cause and save to case memory."""
    from eda_agent.agent.inference.engine import confirm

    result = confirm(inference_id=inference_id, confirmed_cause_id=confirmed_cause_id)

    try:
        with get_db() as db:
            row = db.execute(
                text("SELECT run_id FROM root_cause_inferences WHERE id = :id"),
                {"id": inference_id},
            ).first()
        run_id = int(row[0]) if row and row[0] is not None else None
        if run_id is not None:
            _set_flow_session_context_from_run(
                run_id,
                inference_id=inference_id,
                case_id=result.get("case_id"),
                rule_id=confirmed_cause_id,
            )
    except Exception:
        logger.warning("Failed to persist confirmed inference context", exc_info=True)

    return result


# ── Dispatch table ────────────────────────────────────────────────────────────

_TOOL_DISPATCH = {
    "run_eda_stage": _run_eda_stage,
    "run_eda_flow": _run_eda_flow,
    "run_multi_agent_cycle": _run_multi_agent_cycle_tool,
    "get_run_log": _get_run_log,
    "query_timing": _query_timing,
    "query_congestion": _query_congestion,
    "query_congestion_summary": _query_congestion_summary,
    "query_utilization": _query_utilization,
    "query_power": _query_power,
    "compare_runs": _compare_runs,
    "query_flow_sessions": _query_flow_sessions,
    "query_session_trace": _query_session_trace,
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
    "optimize_with_inference": _optimize_with_inference_tool,
}
def _parse_tool_name_set(raw: str) -> set[str]:
    return {x.strip() for x in raw.split(",") if x.strip()}


def _summarize_arguments(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str):
            out[k] = v if len(v) <= 200 else v[:200] + "..."
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, dict)):
            try:
                encoded = json.dumps(v, ensure_ascii=False)
            except TypeError:
                encoded = str(v)
            out[k] = encoded if len(encoded) <= 300 else encoded[:300] + "..."
        else:
            text_v = str(v)
            out[k] = text_v if len(text_v) <= 200 else text_v[:200] + "..."
    return out


def _audit_custom_tool_call(
    *,
    tool_name: str,
    source: str,
    arguments: dict[str, Any],
    duration_ms: int,
    result: Any = None,
    error: str | None = None,
) -> None:
    exit_code = None
    ok = False
    if isinstance(result, dict):
        raw_exit = result.get("exit_code")
        if isinstance(raw_exit, int):
            exit_code = raw_exit
        raw_ok = result.get("ok")
        ok = bool(raw_ok) if isinstance(raw_ok, bool) else (error is None)
    else:
        ok = error is None

    try:
        _jc = "::jsonb" if is_postgresql() else ""
        with get_db() as db:
            db.execute(
                text(
                    f"""
                    INSERT INTO custom_tool_audit
                        (tool_name, source, arguments_summary, duration_ms,
                         exit_code, ok, error_message)
                    VALUES
                        (:tool_name, :source, :arguments_summary{_jc}, :duration_ms,
                         :exit_code, :ok, :error_message)
                    """
                ),
                {
                    "tool_name": tool_name,
                    "source": source,
                    "arguments_summary": json.dumps(_summarize_arguments(arguments)),
                    "duration_ms": duration_ms,
                    "exit_code": exit_code,
                    "ok": ok,
                    "error_message": (error or "")[:2000],
                },
            )
    except Exception:
        logger.warning("Failed to audit custom tool call: %s", tool_name, exc_info=True)


def _load_custom_tool_bindings() -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    allowlist = _parse_tool_name_set(settings.custom_tools_allowlist)
    denylist = _parse_tool_name_set(settings.custom_tools_denylist)
    reserved = set(_TOOL_DISPATCH.keys())

    schemas: list[dict[str, Any]] = []
    dispatch: dict[str, Any] = {}
    policies: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}

    custom_tools_file = settings.custom_tools_file.strip()
    if custom_tools_file:
        try:
            file_schemas, file_dispatch, file_policies, file_sources = load_custom_tools(
                custom_tools_file,
                reserved_names=reserved,
                allowlist=allowlist or None,
                denylist=denylist or None,
            )
            schemas.extend(file_schemas)
            dispatch.update(file_dispatch)
            policies.update(file_policies)
            sources.update(file_sources)
            reserved.update(file_dispatch.keys())
        except CustomToolConfigError:
            logger.exception("Failed to load custom tools from %s", custom_tools_file)

    if settings.custom_tools_enable_entrypoints:
        try:
            ep_schemas, ep_dispatch, ep_policies, ep_sources = load_custom_tools_from_entry_points(
                group=settings.custom_tools_entrypoint_group,
                reserved_names=reserved,
                allowlist=allowlist or None,
                denylist=denylist or None,
            )
            schemas.extend(ep_schemas)
            dispatch.update(ep_dispatch)
            policies.update(ep_policies)
            sources.update(ep_sources)
        except CustomToolConfigError:
            logger.exception(
                "Failed to load custom tools from entrypoint group %s",
                settings.custom_tools_entrypoint_group,
            )

    return schemas, dispatch, policies, sources


_CUSTOM_TOOL_SCHEMAS, _CUSTOM_TOOL_DISPATCH, _CUSTOM_TOOL_POLICIES, _CUSTOM_TOOL_SOURCES = (
    _load_custom_tool_bindings()
)
if _CUSTOM_TOOL_DISPATCH:
    _TOOL_DISPATCH.update(_CUSTOM_TOOL_DISPATCH)

_CUSTOM_TOOL_NAMES = set(_CUSTOM_TOOL_DISPATCH.keys())

# Register policies at startup so guardrails can enforce custom-tool risk levels.
try:
    from eda_agent.agent.guardrails import register_custom_tool_policies

    register_custom_tool_policies(_CUSTOM_TOOL_POLICIES)
except Exception:
    logger.warning("Failed to register custom tool policies", exc_info=True)

# Exposed to planner/API callers.
TOOL_SCHEMAS = [*BUILTIN_TOOL_SCHEMAS, *_CUSTOM_TOOL_SCHEMAS]


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

    started = perf_counter()
    custom_result: Any = None
    custom_error: str | None = None
    try:
        result = fn(**args)
        if name in _CUSTOM_TOOL_NAMES:
            custom_result = result
        # Attach warnings to result when present
        if gr.level == RiskLevel.WARN and gr.warnings:
            if isinstance(result, dict):
                result["_warnings"] = gr.warnings
            else:
                # Wrap non-dict results
                result = {"result": result, "_warnings": gr.warnings}
        return json.dumps(result, default=str)
    except Exception as exc:
        if name in _CUSTOM_TOOL_NAMES:
            custom_error = str(exc)
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(exc)})
    finally:
        if name in _CUSTOM_TOOL_NAMES:
            _audit_custom_tool_call(
                tool_name=name,
                source=_CUSTOM_TOOL_SOURCES.get(name, "custom"),
                arguments=args,
                duration_ms=max(0, int((perf_counter() - started) * 1000)),
                result=custom_result,
                error=custom_error,
            )


# ── Internal DB helpers ───────────────────────────────────────────────────────

def _upsert_run(
    result: Any,
    design: DesignSpec,
    db: Any = None,
    run_context: dict[str, Any] | None = None,
) -> int:
    """Insert the RunResult into the DB and return the integer PK.

    If *db* is provided the caller manages the transaction; otherwise a new
    session is created and committed independently (backward-compatible path).
    """
    from eda_agent.agent.tool_impl_persistence import upsert_run

    return upsert_run(
        result,
        design,
        db=db,
        run_context=run_context,
        get_db_fn=get_db,
    )


def _upsert_run_impl(
    result: Any,
    design: DesignSpec,
    db: Any,
    run_context: dict[str, Any] | None = None,
) -> int:
    """Persist a RunResult using an active *db* session."""
    from eda_agent.agent.tool_impl_persistence import upsert_run_impl

    return upsert_run_impl(result, design, db, run_context=run_context)


def _upsert_artifacts(run_id: int, reports: list[Any], db: Any = None) -> None:
    """Persist collected report files into artifacts table (best effort).

    If *db* is provided the caller manages the transaction; otherwise a new
    session is created independently.
    """
    from eda_agent.agent.tool_impl_persistence import upsert_artifacts

    upsert_artifacts(run_id, reports, db=db, get_db_fn=get_db)


def _upsert_artifacts_with_db(run_id: int, reports: list[Any], db: Any) -> None:
    """Backward-compat alias — delegates to _upsert_artifacts."""
    from eda_agent.agent.tool_impl_persistence import upsert_artifacts_impl

    upsert_artifacts_impl(run_id, reports, db)


def _upsert_artifacts_impl(run_id: int, reports: list[Any], db: Any) -> None:
    """Internal: persist artifacts using an active *db* session."""
    from eda_agent.agent.tool_impl_persistence import upsert_artifacts_impl

    upsert_artifacts_impl(run_id, reports, db)


def _ingest_records(records: list[dict], run_id: int, stage: str, db: Any = None) -> None:
    """Fan out parsed records into the appropriate DB tables.

    If *db* is provided the caller manages the transaction; otherwise a new
    session is created and committed independently.
    """
    from eda_agent.agent.tool_impl_persistence import ingest_records

    ingest_records(records, run_id, stage, db=db, get_db_fn=get_db)


def _ingest_records_impl(records: list[dict], run_id: int, stage: str, db: Any) -> None:
    """Fan out parsed records using an active *db* session."""
    from eda_agent.agent.tool_impl_persistence import ingest_records_impl

    ingest_records_impl(records, run_id, stage, db)
