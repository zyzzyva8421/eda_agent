"""Async task queue for EDA Agent.

Provides a lightweight SQLite-backed job queue and a background worker
process so that long-running EDA stage invocations (e.g. ``make route``)
do not block the CLI or the HTTP server.

Quick start
-----------
Submit a job from the CLI::

    eda-agent submit --stage route --design aes --pdk sky130hd \\
        --config /path/to/OpenROAD-flow-scripts/flow/designs/sky130hd/aes/config.mk

List / inspect jobs::

    eda-agent list
    eda-agent status <job_id>
    eda-agent logs   <job_id> [--follow]
    eda-agent cancel <job_id>

Start the worker (also auto-started on first submit)::

    eda-agent-worker
"""

from eda_agent.queue.store import Job, JobStatus, JobStore

__all__ = ["Job", "JobStatus", "JobStore"]
