"""Interactive REPL CLI for EDA Agent.

Provides a readline-based conversational shell that lets the user chat directly
with the ReAct planner without going through the HTTP API.

Usage::

    eda-agent          # start interactive REPL
    eda-agent submit   # submit an async EDA job
    eda-agent list     # list submitted jobs
    eda-agent status   # show status of a specific job
    eda-agent logs     # print (or follow) logs for a job
    eda-agent cancel   # cancel a pending job

    eda-agent-server   # start FastAPI/Uvicorn server (see pyproject.toml)
    eda-agent-worker   # start background job worker

Commands inside the REPL
------------------------
    clear    -- clear the current session memory
    history  -- print the current session message history
    exit / quit / Ctrl-D / Ctrl-C  -- exit
"""

from __future__ import annotations

import sys

try:
    import readline as _readline  # noqa: F401 -- imported for side-effect (history)

    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner

_BANNER = """\
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551          EDA Agent  \u2013  Interactive CLI               \u2551
\u2551  Type 'help' for commands, 'exit' to quit.           \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
"""

_HELP = """\
Built-in commands:
  clear    -- reset session memory
  history  -- show message history
  help     -- show this help
  exit     -- quit (also: quit, Ctrl-D, Ctrl-C)

Anything else is forwarded to the EDA ReAct agent.
"""


def _print_history(memory: AgentMemory) -> None:
    msgs = memory.get_messages()
    if not msgs:
        print("(empty session)")
        return
    for i, m in enumerate(msgs, 1):
        role = m.get("role", "?").upper()
        content = m.get("content") or ""
        print(f"[{i}] {role}: {content[:200]}")


def cli_repl() -> None:
    """Entry point for the interactive ``eda-agent`` REPL."""
    print(_BANNER)
    planner = Planner()
    memory = AgentMemory()

    while True:
        try:
            user_input = input("eda-agent> ").strip()
        except EOFError:
            print("\nGoodbye!")
            break
        except KeyboardInterrupt:
            print("\n(Interrupted -- type 'exit' to quit)")
            continue

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit"):
            print("Goodbye!")
            break
        if cmd == "clear":
            memory.clear()
            print("Session cleared.")
            continue
        if cmd == "history":
            _print_history(memory)
            continue
        if cmd == "help":
            print(_HELP)
            continue

        try:
            reply = planner.run(user_input, memory=memory)
            print(f"\nAgent: {reply}\n")
        except (RuntimeError, ValueError, OSError, TimeoutError) as exc:
            print(f"Error: {exc}\n", file=sys.stderr)


# ---------------------------------------------------------------------------
# Job sub-commands (eda-agent submit / list / status / logs / cancel)
# ---------------------------------------------------------------------------


def _build_parser():
    """Build the top-level argument parser for job subcommands."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="eda-agent",
        description=(
            "EDA Agent CLI.  Run without arguments to enter the interactive REPL.\n"
            "Use a subcommand to manage async EDA jobs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # -- submit ----------------------------------------------------------------
    sp = sub.add_parser("submit", help="Submit an EDA stage job to the async queue.")
    sp.add_argument("--backend", default="orfs", help="Backend name (default: orfs).")
    sp.add_argument("--stage", required=True, help="Flow stage (e.g. synth, route).")
    sp.add_argument(
        "--design",
        required=True,
        dest="design_name",
        metavar="DESIGN",
        help="Top-level design name (e.g. aes).",
    )
    sp.add_argument(
        "--config",
        required=True,
        dest="design_config",
        metavar="PATH",
        help="Absolute path to the design config file (ORFS: config.mk).",
    )
    sp.add_argument("--pdk", default="sky130hd", help="PDK identifier (default: sky130hd).")
    sp.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra make/tool parameter override; may be repeated.",
    )
    sp.add_argument(
        "--no-worker",
        action="store_true",
        help="Do not auto-start the background worker.",
    )

    # -- list ------------------------------------------------------------------
    lp = sub.add_parser("list", help="List submitted jobs.")
    lp.add_argument(
        "--status",
        default=None,
        metavar="STATUS",
        help="Filter by status (pending|running|success|failed|cancelled).",
    )

    # -- status ----------------------------------------------------------------
    stp = sub.add_parser("status", help="Show the status of a specific job.")
    stp.add_argument("job_id", help="Job UUID returned by 'submit'.")

    # -- logs ------------------------------------------------------------------
    lgp = sub.add_parser("logs", help="Print logs for a job.")
    lgp.add_argument("job_id", help="Job UUID.")
    lgp.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="Keep following the log file (like tail -f).",
    )

    # -- cancel ----------------------------------------------------------------
    cp = sub.add_parser("cancel", help="Cancel a pending job.")
    cp.add_argument("job_id", help="Job UUID.")

    return parser


def _parse_params(param_list: list[str]) -> dict:
    """Parse ``KEY=VALUE`` strings into a dict."""
    result: dict = {}
    for item in param_list:
        if "=" not in item:
            print(
                f"Warning: ignoring malformed --param '{item}' (expected KEY=VALUE)",
                file=sys.stderr,
            )
            continue
        k, v = item.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def _ensure_worker(no_worker: bool = False) -> None:
    """Auto-launch the background worker if it is not already running."""
    if no_worker:
        return

    from eda_agent.queue.worker import _WORKER_LOG, is_worker_running

    if is_worker_running():
        return

    import subprocess

    _WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_WORKER_LOG, "a") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "eda_agent.queue.worker"],
            stdout=log_fh,
            stderr=log_fh,
            close_fds=True,
            start_new_session=True,
        )
    print(f"[worker] Started background worker (PID={proc.pid}), logs -> {_WORKER_LOG}")


# -- command implementations ---------------------------------------------------


def _cmd_submit(args) -> None:
    from eda_agent.queue.store import JobStore

    params = _parse_params(args.param)
    store = JobStore()
    job = store.create_job(
        backend=args.backend,
        stage=args.stage,
        design_name=args.design_name,
        design_config=args.design_config,
        pdk=args.pdk,
        params=params,
    )
    print(f"Job submitted: {job.job_id}")
    print(f"  backend : {job.backend}")
    print(f"  stage   : {job.stage}")
    print(f"  design  : {job.design_name}  (pdk={job.pdk})")
    print(f"  config  : {job.design_config}")
    if params:
        print(f"  params  : {params}")
    print(f"  status  : {job.status.value}")
    _ensure_worker(no_worker=args.no_worker)
    print(f"\nUse 'eda-agent status {job.job_id}' to check progress.")


def _cmd_list(args) -> None:
    from eda_agent.queue.store import JobStatus, JobStore

    status_filter = None
    if args.status:
        try:
            status_filter = JobStatus(args.status.lower())
        except ValueError:
            valid = ", ".join(s.value for s in JobStatus)
            print(
                f"Error: unknown status '{args.status}'. Valid values: {valid}",
                file=sys.stderr,
            )
            sys.exit(1)

    store = JobStore()
    jobs = store.list_jobs(status=status_filter)

    if not jobs:
        print("No jobs found.")
        return

    print(
        f"{'JOB ID':36}  {'STATUS':10}  {'STAGE':10}  "
        f"{'DESIGN':16}  {'PDK':12}  CREATED"
    )
    print("-" * 110)
    for j in jobs:
        created = j.created_at.strftime("%Y-%m-%d %H:%M:%S") if j.created_at else ""
        print(
            f"{j.job_id:36}  {j.status.value:10}  {j.stage:10}  "
            f"{j.design_name:16}  {j.pdk:12}  {created}"
        )


def _cmd_status(args) -> None:
    from eda_agent.queue.store import JobStore

    store = JobStore()
    job = store.get_job(args.job_id)
    if job is None:
        print(f"Error: job '{args.job_id}' not found.", file=sys.stderr)
        sys.exit(1)

    def _fmt(dt):
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z") if dt else "--"

    print(f"Job ID    : {job.job_id}")
    print(f"Status    : {job.status.value}")
    print(f"Backend   : {job.backend}")
    print(f"Stage     : {job.stage}")
    print(f"Design    : {job.design_name}  (pdk={job.pdk})")
    print(f"Config    : {job.design_config}")
    if job.params:
        print(f"Params    : {job.params}")
    print(f"Created   : {_fmt(job.created_at)}")
    print(f"Started   : {_fmt(job.started_at)}")
    print(f"Finished  : {_fmt(job.finished_at)}")
    if job.run_db_id is not None:
        print(f"Run DB ID : {job.run_db_id}")
    if job.log_path:
        print(f"Log path  : {job.log_path}")
    if job.error_message:
        print(f"Error     : {job.error_message}")
    if job.worker_pid:
        print(f"Worker PID: {job.worker_pid}")


def _cmd_logs(args) -> None:
    import time
    from pathlib import Path

    from eda_agent.queue.store import JobStatus, JobStore

    store = JobStore()
    job = store.get_job(args.job_id)
    if job is None:
        print(f"Error: job '{args.job_id}' not found.", file=sys.stderr)
        sys.exit(1)

    # Wait until a log path is available (job may still be pending)
    if job.log_path is None and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        print("Waiting for job to start and produce a log file...")
        for _ in range(60):  # wait up to 60 s
            time.sleep(1)
            job = store.get_job(args.job_id)
            if job and job.log_path:
                break
        else:
            print("Timed out waiting for log file.", file=sys.stderr)
            sys.exit(1)

    if not job or not job.log_path:
        print("No log file available for this job.", file=sys.stderr)
        sys.exit(1)

    log_path = Path(job.log_path)
    if not log_path.exists():
        print(f"Log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    if not args.follow:
        print(log_path.read_text(errors="replace"))
        return

    # --follow: stream new content until job finishes
    print(f"==> {log_path} <==")
    try:
        with log_path.open(errors="replace") as fh:
            while True:
                line = fh.readline()
                if line:
                    print(line, end="")
                else:
                    # Check if the job is still running
                    current = store.get_job(args.job_id)
                    if current and current.status in (JobStatus.PENDING, JobStatus.RUNNING):
                        time.sleep(0.5)
                    else:
                        break
    except KeyboardInterrupt:
        pass


def _cmd_cancel(args) -> None:
    from eda_agent.queue.store import JobStore

    store = JobStore()
    ok = store.cancel_job(args.job_id)
    if ok:
        print(f"Job {args.job_id} cancelled.")
    else:
        job = store.get_job(args.job_id)
        if job is None:
            print(f"Error: job '{args.job_id}' not found.", file=sys.stderr)
        else:
            print(
                f"Cannot cancel job with status '{job.status.value}'. "
                "Only pending jobs can be cancelled.",
                file=sys.stderr,
            )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Primary entry point -- dispatches to subcommand or interactive REPL."""
    # No arguments: launch the interactive REPL (backward-compatible)
    if len(sys.argv) == 1:
        cli_repl()
        return

    parser = _build_parser()
    args = parser.parse_args()

    dispatch = {
        "submit": _cmd_submit,
        "list": _cmd_list,
        "status": _cmd_status,
        "logs": _cmd_logs,
        "cancel": _cmd_cancel,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)
