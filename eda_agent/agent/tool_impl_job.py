"""Implementation helpers for async run/job tool operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def submit_job_impl(
    *,
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
    resolve_identity_fn: Callable[..., tuple[str, str]],
    ensure_worker_running_fn: Callable[[], None],
    on_worker_start_error: Callable[[Exception], None] | None = None,
) -> dict[str, Any]:
    """Submit an async job to the queue (stage or flow mode)."""
    from eda_agent.queue.store import JobStore

    if run_mode not in ("stage", "flow"):
        return {"error": f"Invalid run_mode '{run_mode}'. Use 'stage' or 'flow'."}

    if run_mode == "stage" and not stage:
        return {"error": "'stage' is required when run_mode='stage'"}

    design_config, pdk = resolve_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

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
        ensure_worker_running_fn()
    except Exception as exc:
        # Keep behavior best-effort and non-failing.
        if on_worker_start_error is not None:
            on_worker_start_error(exc)

    return {
        "job_id": job_id,
        "status": "pending",
        "message": f"Job {job_id} submitted ({run_mode} mode). Use job_status to poll.",
    }


def run_eda_flow_async_impl(
    *,
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
    resolve_identity_fn: Callable[..., tuple[str, str]],
    submit_job_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Submit a flow job asynchronously and return job metadata."""
    if clean:
        params = params or {}
        params["_clean"] = True

    design_config, pdk = resolve_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    return submit_job_fn(
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


def job_status_impl(job_id: str) -> dict[str, Any]:
    from eda_agent.queue.store import JobStatus, JobStore

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


def job_logs_impl(job_id: str, lines: int = 50) -> dict[str, Any]:
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


def cancel_job_impl(job_id: str) -> dict[str, Any]:
    from eda_agent.queue.store import JobStatus, JobStore

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
