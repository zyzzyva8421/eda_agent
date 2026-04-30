"""Background worker process for the EDA Agent async task queue.

The worker polls a :class:`~eda_agent.queue.store.JobStore` for pending
jobs and executes them one at a time by calling
:func:`~eda_agent.agent.tools._run_eda_stage`.

Lifecycle
---------
1. ``eda-agent submit`` writes a job to SQLite and auto-spawns this worker
   as a detached background process if one is not already running.
2. The worker writes its PID to ``~/.eda_agent/worker.pid``.
3. On ``SIGTERM``/``SIGINT`` the worker removes the PID file and exits.
4. If ``--max-idle N`` is set, the worker exits after N seconds with no jobs
   (useful for CI / testing).

Entry point
-----------
``eda-agent-worker`` (console script defined in *pyproject.toml*).
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

from eda_agent.queue.store import JobStatus, JobStore

logger = logging.getLogger(__name__)

_PID_FILE: Path = Path.home() / ".eda_agent" / "worker.pid"
_WORKER_LOG: Path = Path.home() / ".eda_agent" / "worker.log"


# ---------------------------------------------------------------------------
# PID-file helpers (used by CLI to detect a running worker)
# ---------------------------------------------------------------------------


def _write_pid_file() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _remove_pid_file() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def is_worker_running() -> bool:
    """Return ``True`` if a worker process is alive (via PID file)."""
    if not _PID_FILE.exists():
        return False
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 probes for existence without killing
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        _remove_pid_file()
        return False


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


def _execute_job(job, store: JobStore) -> None:
    """Execute *job* and update its record in *store*."""
    # Lazy import: avoids pulling in SQLAlchemy + DB connections at worker
    # startup (relevant when the DB isn't available yet).
    from eda_agent.agent.tools import _run_eda_stage  # noqa: PLC0415

    logger.info(
        "Executing job %s  backend=%s stage=%s design=%s",
        job.job_id,
        job.backend,
        job.stage,
        job.design_name,
    )
    try:
        # Choose execution mode based on job.run_mode
        if job.run_mode == "flow":
            from eda_agent.agent.tools import _run_eda_flow_sync  # noqa: PLC0415

            result = _run_eda_flow_sync(
                backend=job.backend,
                stage_start=job.stage_start or "all",
                stage_end=job.stage_end,
                design_name=job.design_name,
                design_config=job.design_config,
                pdk=job.pdk,
                params=job.params,
            )
            overall = result.get("overall_status", "failed")
            final_status = JobStatus.SUCCESS if overall == "success" else JobStatus.FAILED
            # For flow, use the last stage's run_id and log_path as the primary
            run_db_id = None
            log_path = None
            for r in result.get("results", []):
                if r.get("run_id"):
                    run_db_id = r["run_id"]
                if r.get("log_path"):
                    log_path = r["log_path"]
            store.mark_done(
                job.job_id,
                status=final_status,
                run_db_id=run_db_id,
                log_path=log_path,
                error_message=result.get("error") or "",
            )
        else:
            # Single stage mode (original behavior)
            from eda_agent.agent.tools import _run_eda_stage  # noqa: PLC0415

            result = _run_eda_stage(
                backend=job.backend,
                stage=job.stage,
                design_name=job.design_name,
                design_config=job.design_config,
                pdk=job.pdk,
                params=job.params,
            )
            final_status = (
                JobStatus.SUCCESS if result.get("status") == "success" else JobStatus.FAILED
            )
            store.mark_done(
                job.job_id,
                status=final_status,
                run_db_id=result.get("run_id"),
                log_path=result.get("log_path"),
                error_message=result.get("error") or "",
            )
        logger.info("Job %s finished → %s", job.job_id, final_status.value)
    except Exception as exc:
        logger.exception("Job %s raised an unhandled exception", job.job_id)
        store.mark_done(
            job.job_id,
            status=JobStatus.FAILED,
            error_message=str(exc),
        )


# ---------------------------------------------------------------------------
# Main worker loop
# ---------------------------------------------------------------------------


def run_worker(
    poll_interval: float = 5.0,
    max_idle_seconds: float | None = None,
    db_path: Path | None = None,
) -> None:
    """Poll for pending jobs and execute them sequentially.

    Parameters
    ----------
    poll_interval:
        Seconds to sleep between polls when the queue is empty.
    max_idle_seconds:
        Exit after the queue has been continuously empty for this many
        seconds.  ``None`` means run forever.
    db_path:
        Override the default SQLite database path (useful for testing).
    """
    store = JobStore(db_path) if db_path else JobStore()
    _write_pid_file()

    # ── signal handlers ──────────────────────────────────────────────────
    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Worker received signal %d, shutting down.", signum)
        _remove_pid_file()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("EDA Agent worker started (PID=%d, db=%s)", os.getpid(), store._db_path)

    idle_since: float | None = None
    try:
        while True:
            job = store.claim_pending_job()
            if job is not None:
                idle_since = None
                _execute_job(job, store)
            else:
                now = time.monotonic()
                if idle_since is None:
                    idle_since = now
                elif max_idle_seconds is not None and (now - idle_since) >= max_idle_seconds:
                    logger.info(
                        "Worker idle for %.0f s with no jobs; exiting.", max_idle_seconds
                    )
                    break
                time.sleep(poll_interval)
    finally:
        _remove_pid_file()


# ---------------------------------------------------------------------------
# Console-script entry point
# ---------------------------------------------------------------------------


def worker_main() -> None:
    """Entry point for the ``eda-agent-worker`` console script."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="eda-agent-worker",
        description="EDA Agent background worker – processes queued EDA jobs.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        metavar="SECS",
        help="Polling interval in seconds when queue is empty (default: 5).",
    )
    parser.add_argument(
        "--max-idle",
        type=float,
        default=None,
        metavar="SECS",
        help="Exit after SECS idle seconds with no pending jobs (default: run forever).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    run_worker(poll_interval=args.poll_interval, max_idle_seconds=args.max_idle)
