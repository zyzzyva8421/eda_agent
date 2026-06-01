"""Interactive REPL CLI for EDA Agent.

Provides a readline-based conversational shell that lets the user chat directly
with the ReAct planner without going through the HTTP API.

Usage::

    eda-agent                       # resume the default CLI session
    eda-agent --session demo        # use / create a named session
    eda-agent --new                 # start a fresh random session
    eda-agent --resume              # pick from recent sessions
    eda-agent --no-persist          # one-off, do not read/write the DB
    eda-agent submit ...            # submit an async EDA job

    eda-agent-server                # start FastAPI/Uvicorn server
    eda-agent-worker                # start background job worker

Session memory
--------------
The REPL persists conversation history *and* derived facts
(design_name / pdk / config_path …) to the ``agent_sessions`` PostgreSQL
table.  Closing the REPL and re-launching it resumes the same default
session automatically, so you can keep working where you left off.  Use
``--session <id>`` to keep multiple parallel threads, or ``forget`` to
wipe a session.  When the DB is unreachable the REPL silently falls back
to an in-memory session (same behaviour as before).

Commands inside the REPL
------------------------
    /clear             -- drop message history (keep design context)
    /forget            -- drop EVERYTHING and delete the row from the DB
    /history [--full]  -- print message history (default: 200-char preview)
    /sessions          -- list recent sessions for the current user
    /session <id>      -- switch to / create another session
    /cd <dir>          -- change the working directory
    /help              -- show command help
    '\"\"\"'          -- start / end a multi-line input block
    !<shell_cmd>       -- run a shell command (e.g. ``!ls -la``, ``!pwd``)
    exit / quit / Ctrl-D  -- exit

Tab Completion:
------------------------
    Press Tab to autocomplete built-in commands (/clear, /history, /help, /cd).
    Tab also completes file/directory paths for any argument.
    When using the ``!`` prefix, Tab completes executables from PATH and paths.
    Use up/down arrow keys to navigate command history.
    The CLI maintains persistent history across sessions.
"""

from __future__ import annotations

import argparse
import atexit
import getpass
import glob as _glob
import logging
import os
import subprocess
import sys
import uuid

try:
    import readline as _readline  # noqa: F401 -- imported for side-effect (history)

    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner
from eda_agent.agent.session_store import (
    clear_session,
    default_cli_session_id,
    list_sessions,
    load_session,
    open_db,
    save_session,
)
from eda_agent.console import Console, Spinner

# Built-in commands for tab completion
_BUILTIN_COMMANDS = [
    "/cd",
    "/clear",
    "/exit",
    "/forget",
    "/help",
    "/history",
    "/quit",
    "/session",
    "/sessions",
    "exit",
    "quit",
]

# History file path for persistent readline history
_HISTORY_FILE = os.path.expanduser("~/.eda_agent_history")
_MULTILINE_SENTINEL = '"""'


def _complete_cmd_name(prefix: str) -> list[str]:
    """Return executables found in PATH whose names start with *prefix*."""
    matches: list[str] = []
    seen: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        try:
            for name in os.listdir(directory):
                if name.startswith(prefix) and name not in seen:
                    full = os.path.join(directory, name)
                    if os.access(full, os.X_OK):
                        matches.append(name)
                        seen.add(name)
        except OSError:
            pass
    return sorted(matches)


def _path_completions(text: str) -> list[str]:
    """Return filesystem path completions for *text* using glob expansion."""
    expanded = os.path.expanduser(text)
    results: list[str] = []
    for match in sorted(_glob.glob(expanded + "*")):
        display = match
        # Restore the tilde prefix if the user typed it
        if text.startswith("~") and not expanded.startswith("~"):
            home = os.path.expanduser("~")
            if display.startswith(home):
                display = "~" + display[len(home):]
        if os.path.isdir(match) and not display.endswith("/"):
            display += "/"
        results.append(display)
    return results


def _setup_readline():
    """Configure readline with tab completion and load persistent history."""
    if not _HAS_READLINE:
        return
    if not sys.stdin.isatty():
        return

    def completer(text, state):
        line = _readline.get_line_buffer()
        stripped = line.lstrip()

        results: list[str] = []

        if stripped.startswith("!"):
            # Shell-command mode: complete executable names for first token,
            # paths for subsequent tokens.
            inner = stripped[1:]
            parts = inner.split()
            # Two cases for completing the first token:
            #   (1) nothing typed after '!' yet — parts is empty
            #   (2) exactly one word typed with no trailing space — still in progress
            completing_first_token = not parts or (len(parts) == 1 and not inner.endswith(" "))
            if completing_first_token:
                results.extend(cmd for cmd in _complete_cmd_name(text) if cmd.startswith(text))
            results.extend(_path_completions(text))
        elif not stripped or (not line.endswith(" ") and " " not in stripped):
            # Completing the first (and only so far) word on the line.
            results.extend(cmd for cmd in _BUILTIN_COMMANDS if cmd.startswith(text))
        else:
            # Completing a subsequent argument — offer path completions.
            results.extend(_path_completions(text))
            if not results:
                results.extend(_path_completions("./" + text))

        if state < len(results):
            return results[state]
        return None

    _readline.set_completer(completer)
    # Word delimiters: spaces and common shell separators split tokens.
    # Forward slashes are intentionally *excluded* so that full paths like
    # /usr/local/bin or ~/projects/chip are treated as a single completable token.
    _readline.set_completer_delims(" \t\n;|&")
    _readline.parse_and_bind("tab: complete")

    # Emacs editing mode: arrow keys ↑/↓ navigate history out of the box.
    _readline.parse_and_bind("set editing-mode emacs")

    # Load persistent history
    if os.path.exists(_HISTORY_FILE):
        _readline.read_history_file(_HISTORY_FILE)

    # Save history on exit
    atexit.register(_save_history)


def _save_history():
    """Save readline history to file."""
    if _HAS_READLINE:
        _readline.write_history_file(_HISTORY_FILE)

_BANNER = """\
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551          EDA Agent  \u2013  Interactive CLI               \u2551
\u2551  Type '/help' for commands, 'exit' to quit.          \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
"""

_HELP = """\
Built-in commands:
    /clear             -- drop message history (keep design context)
    /forget            -- drop EVERYTHING and delete this session from the DB
    /history [--full]  -- show message history (default: 200-char preview)
    /sessions          -- list recent sessions for your user
    /session <id>      -- switch to / create another session
    /cd <dir>          -- change working directory
    /help              -- show this help
    exit               -- quit (also: quit, Ctrl-D)

Multi-line input:
    '\"\"\"'          -- start a multi-line block; enter '\"\"\"' again to send it

Shell commands:
  !<cmd> [args]  -- run a shell command (e.g. !ls -la, !pwd, !cat file.txt)

Keyboard shortcuts:
  ↑ / ↓          -- navigate command history
  Tab             -- autocomplete commands, executables, and paths

Anything else is forwarded to the EDA ReAct agent.
"""


def _print_history(memory: AgentMemory, full: bool = False) -> None:
    msgs = memory.get_messages()
    if not msgs:
        print("(empty session)")
        return
    for i, m in enumerate(msgs, 1):
        role = m.get("role", "?").upper()
        content = m.get("content") or ""
        if not full and len(content) > 200:
            hidden = len(content) - 200
            content = content[:200] + f"... [truncated {hidden} chars]"
        print(f"[{i}] {role}: {content}")


def _current_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "anon"


def _print_banner(memory: AgentMemory, session_id: str, persistent: bool) -> None:
    print(_BANNER)
    ctx = memory.extract_design_context()
    persistence_note = "DB-backed" if persistent else "in-memory only (--no-persist)"
    summary = f"session: {session_id}  ({persistence_note}, {len(memory)} msg)"
    print(f"  {summary}")
    if ctx:
        design = ctx.get("design_name") or "?"
        pdk = ctx.get("pdk") or "?"
        print(f"  context: design={design}, pdk={pdk}")
    print(f"  cwd: {os.getcwd()}")
    print()


def _build_prompt(memory: AgentMemory, session_id: str) -> str:
    ctx = memory.extract_design_context()
    parts = [session_id]
    design = ctx.get("design_name") if ctx else None
    pdk = ctx.get("pdk") if ctx else None
    if design or pdk:
        parts.append(f"{design or '?'}@{pdk or '?'}")
    cwd = os.path.basename(os.getcwd()) or os.getcwd()
    parts.append(cwd)
    return f"eda-agent [{' | '.join(parts)}]> "


def _parse_slash_command(user_input: str) -> tuple[str, str] | None:
    stripped = user_input.strip()
    if not stripped.startswith("/"):
        return None
    body = stripped[1:].strip()
    if not body:
        return ("help", "")
    name, _, arg_text = body.partition(" ")
    return (name.lower(), arg_text.strip())


def _read_repl_input(prompt: str) -> str | None:
    first = input(prompt)
    if first.strip() != _MULTILINE_SENTINEL:
        return first.strip()

    print("(multi-line mode; finish with \"\"\")")
    lines: list[str] = []
    while True:
        try:
            line = input("... ")
        except (EOFError, KeyboardInterrupt):
            print("\n(multi-line input cancelled)")
            return None
        if line.strip() == _MULTILINE_SENTINEL:
            return "\n".join(lines).strip()
        lines.append(line)


def _format_repl_error(exc: Exception, *, verbose: int) -> str:
    message = f"{type(exc).__name__}: {exc}".strip()
    lowered = str(exc).lower()
    suggestion = "Retry with a narrower request."

    if isinstance(exc, TimeoutError):
        suggestion = "Operation timed out. Retry, or narrow the scope before rerunning."
    elif isinstance(exc, (ConnectionError, OSError)) or any(
        token in lowered
        for token in ("connection refused", "temporary failure", "name or service not known", "network")
    ):
        suggestion = "Connection failed. Check the configured LLM/API/backend service and network reachability."
    elif any(
        token in lowered
        for token in ("api key", "authentication", "unauthorized", "forbidden", "401", "403")
    ):
        suggestion = "Authentication failed. Check the model/API credentials in your environment."
    elif any(
        token in lowered
        for token in ("quota", "rate limit", "429", "insufficient_quota")
    ):
        suggestion = "Quota or rate limit reached. Check provider limits or retry later."
    elif isinstance(exc, ValueError):
        suggestion = "Input validation failed. Check the request arguments or current design context."
    elif isinstance(exc, KeyError):
        suggestion = "Agent state was incomplete. Retry once; if it repeats, rerun with -vv to inspect the traceback."

    if verbose < 2 and "-vv" not in suggestion:
        suggestion = f"{suggestion} Rerun with -vv for traceback."
    return f"{message}. {suggestion}"


def _pick_resume_session(username: str, db) -> str | None:
    """Interactively let the user pick a recent session.  Returns the id."""
    sessions = list_sessions(username, db, limit=10)
    if not sessions:
        print("No previous sessions found for", username)
        return None
    print("Recent sessions:")
    for i, s in enumerate(sessions, 1):
        ts = s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else "?"
        print(f"  [{i}] {s.session_id}  ({s.message_count} msg, last {ts})")
    try:
        choice = input("Pick a number (Enter = cancel): ").strip()
    except EOFError:
        return None
    if not choice:
        return None
    try:
        idx = int(choice)
    except ValueError:
        return None
    if 1 <= idx <= len(sessions):
        return sessions[idx - 1].session_id
    return None


def _configure_logging(verbose: int, quiet: bool) -> None:
    """Initialise root logging based on CLI flags / ``EDA_AGENT_LOG``.

    Resolution order (highest priority first):

    1. Explicit log level in ``EDA_AGENT_LOG`` (e.g. ``DEBUG``, ``INFO``).
    2. ``--quiet`` → ``ERROR``.
    3. ``--verbose`` count (``-v`` → ``INFO``, ``-vv`` and up → ``DEBUG``).
    4. Default → ``WARNING``.
    """
    env_level = os.environ.get("EDA_AGENT_LOG")
    if env_level:
        level = getattr(logging, env_level.upper(), None)
        if not isinstance(level, int):
            level = logging.INFO
    elif quiet:
        level = logging.ERROR
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    # Re-configure even if called more than once so the user can flip
    # verbosity by relaunching the REPL.  ``force=True`` was added in 3.8
    # and is safe to use unconditionally.
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # Quiet noisy third-party libraries unless the user explicitly opted
    # in to DEBUG.
    if level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def cli_repl(
    session_id: str | None = None,
    new: bool = False,
    resume: bool = False,
    no_persist: bool = False,
    verbose: int = 0,
    quiet: bool = False,
    stream: bool = False,
) -> None:
    """Entry point for the interactive ``eda-agent`` REPL.

    Parameters
    ----------
    session_id:
        Explicit session identifier; defaults to ``cli-<user>-default``
        when no flag is provided so consecutive launches resume the same
        conversation.
    new:
        Force a brand-new random session id (ignores stored history).
    resume:
        Show a picker of recent sessions before starting.
    no_persist:
        Do not read or write the ``agent_sessions`` table; useful for
        throwaway debugging sessions.
    verbose:
        Verbosity counter from ``-v`` / ``-vv``.  Controls logging level
        and step-by-step ReAct event output.
    quiet:
        Suppress progress lines (and lower the log level to ``ERROR``)
        so only final replies and errors are written.
    stream:
        Stream the final assistant message via SSE when supported.  When
        the LLM still wants to call tools the planner falls back to the
        non-streaming path for that turn automatically.
    """
    _configure_logging(verbose=verbose, quiet=quiet)
    console = Console(quiet=quiet, show_events=(verbose >= 1 and not quiet))
    _setup_readline()
    planner = Planner()

    username = _current_username()
    db = None if no_persist else open_db()

    if resume:
        picked = _pick_resume_session(username, db)
        if picked:
            session_id = picked
        elif session_id is None and not new:
            session_id = default_cli_session_id(username)

    if new:
        session_id = f"cli-{username}-{uuid.uuid4().hex[:8]}"
    elif session_id is None:
        session_id = default_cli_session_id(username)

    memory = load_session(session_id, db) if db is not None else AgentMemory()

    def _persist() -> None:
        if db is not None:
            save_session(session_id, username, memory, db)

    atexit.register(_persist)

    _print_banner(memory, session_id, persistent=db is not None)

    while True:
        try:
            user_input = _read_repl_input(_build_prompt(memory, session_id))
        except EOFError:
            print("\nGoodbye!")
            break
        except KeyboardInterrupt:
            print("\n(Cancelled input; use Ctrl-D or 'exit' to quit)")
            continue

        if not user_input:
            continue

        cmd = user_input.strip().lower()
        slash_cmd = _parse_slash_command(user_input)

        if cmd in ("exit", "quit") or slash_cmd in {("exit", ""), ("quit", "")}:
            print("Goodbye!")
            break

        if slash_cmd is not None:
            name, arg_text = slash_cmd
            if name == "clear":
                memory.clear()
                _persist()
                print("Message history cleared. (Design context preserved -- use '/forget' to wipe everything.)")
                continue
            if name == "forget":
                try:
                    confirm = input(
                        f"This will permanently delete session '{session_id}' "
                        f"and all its history.  Type 'yes' to confirm: "
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\n/forget: cancelled.")
                    continue
                if confirm != "yes":
                    print("/forget: cancelled.")
                    continue
                memory.forget()
                clear_session(session_id, db)
                print(f"Session '{session_id}' wiped.")
                continue
            if name == "history":
                parts = arg_text.split()
                full = bool(parts) and parts[0] in ("--full", "-f", "full")
                _print_history(memory, full=full)
                continue
            if name == "sessions":
                entries = list_sessions(username, db, limit=20)
                if not entries:
                    print("(no sessions)" if db is not None else "(persistence disabled)")
                else:
                    for s in entries:
                        ts = s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else "?"
                        marker = "*" if s.session_id == session_id else " "
                        print(f" {marker} {s.session_id:40s}  {s.message_count:>4d} msg  {ts}")
                continue
            if name == "session":
                new_sid = arg_text.strip()
                if not new_sid:
                    print("Usage: /session <id>", file=sys.stderr)
                    continue
                _persist()
                session_id = new_sid
                memory = load_session(session_id, db) if db is not None else AgentMemory()
                print(f"Switched to session '{session_id}' ({len(memory)} msg).")
                continue
            if name == "help":
                print(_HELP)
                continue
            if name == "cd":
                target = arg_text or os.path.expanduser("~")
                target = os.path.expanduser(target.strip())
                try:
                    os.chdir(target)
                    print(os.getcwd())
                except OSError as exc:
                    print(f"cd: {exc}", file=sys.stderr)
                continue
            print(f"Unknown command '/{name}'. Type '/help' for available commands.", file=sys.stderr)
            continue

        if user_input.startswith("!"):
            shell_cmd = user_input[1:].strip()
            if not shell_cmd:
                print("Usage: !<command>  (e.g. !ls -la)", file=sys.stderr)
                continue
            first_token = shell_cmd.split(None, 1)[0] if shell_cmd else ""
            if first_token == "cd":
                print("Use the built-in '/cd' command to change the REPL working directory.", file=sys.stderr)
                continue
            try:
                subprocess.run(shell_cmd, shell=True)  # noqa: S602
            except OSError as exc:
                print(f"Error running command: {exc}", file=sys.stderr)
            continue

        try:
            def _emit(kind: str, payload: dict) -> None:
                console.event(kind, payload)

            with Spinner(console, text="thinking"):
                reply = planner.run(
                    user_input,
                    memory=memory,
                    on_event=_emit,
                    stream=stream,
                )
            console.agent(reply)
            _persist()
        except KeyboardInterrupt:
            console.info("(cancelled current turn)")
            _persist()
        except Exception as exc:  # noqa: BLE001 -- REPL must stay alive across any planner error
            console.error(_format_repl_error(exc, verbose=verbose))
            logging.getLogger(__name__).debug("planner.run raised", exc_info=True)
            # Persist whatever we have so far so transient failures don't
            # cost the user their conversation context.
            _persist()


# ---------------------------------------------------------------------------
# Job sub-commands (eda-agent submit / list / status / logs / cancel)
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Return the installed package version, falling back to 'unknown'."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("eda_agent")
    except PackageNotFoundError:
        return "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _build_parser():
    """Build the top-level argument parser for job subcommands."""
    parser = argparse.ArgumentParser(
        prog="eda-agent",
        description=(
            "EDA Agent CLI.  Run without arguments to enter the interactive REPL.\n"
            "Use a subcommand to manage async EDA jobs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    # REPL-mode flags (only used when no subcommand is given).
    parser.add_argument(
        "--session",
        default=None,
        metavar="ID",
        help="Resume / create a named REPL session (default: cli-<user>-default).",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Start a brand-new REPL session (ignores stored history).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Pick a previous REPL session from a list.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not read or write the agent_sessions DB table.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v: INFO + ReAct steps, -vv: DEBUG).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print final replies / errors (sets log level to ERROR).",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream the final assistant reply token-by-token (best-effort SSE).",
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
    sp.add_argument(
        "--clean",
        action="store_true",
        help="Run 'make clean' before the target stage (forces rerun).",
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

    # -- doctor ----------------------------------------------------------------
    sub.add_parser(
        "doctor",
        help="Run environment checks (API key, PostgreSQL, ORFS, …) and report issues.",
    )

    # -- wait ------------------------------------------------------------------
    wp = sub.add_parser(
        "wait",
        help="Block until a job reaches a terminal state. Exit 0 on success, "
        "non-zero on failure / cancellation / timeout.",
    )
    wp.add_argument("job_id", help="Job UUID returned by 'submit'.")
    wp.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Maximum seconds to wait (default: no timeout).",
    )
    wp.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Poll interval in seconds (default: 2).",
    )
    wp.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output; only set exit code.",
    )

    # -- cancel ----------------------------------------------------------------
    cp = sub.add_parser("cancel", help="Cancel pending job(s).")
    cp.add_argument(
        "job_id",
        nargs="?",
        default=None,
        help="Job UUID. You can also pass 'all' to cancel all pending jobs.",
    )
    cp.add_argument(
        "--all",
        action="store_true",
        help="Cancel all pending jobs.",
    )

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

    import subprocess
    from eda_agent.config import settings
    from eda_agent.queue.worker import _WORKER_LOG, is_worker_running

    if is_worker_running():
        return

    # Pass essential env vars to worker (ORFS_ROOT, DB credentials, etc.)
    env = subprocess.os.environ.copy()
    env["ORFS_ROOT"] = str(settings.orfs_root)
    env["POSTGRES_HOST"] = settings.postgres_host
    env["POSTGRES_PORT"] = str(settings.postgres_port)
    env["POSTGRES_USER"] = settings.postgres_user
    env["POSTGRES_PASSWORD"] = settings.postgres_password
    env["POSTGRES_DB"] = settings.postgres_db

    _WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_WORKER_LOG, "a") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "eda_agent.queue.worker"],
            stdout=log_fh,
            stderr=log_fh,
            close_fds=True,
            start_new_session=True,
            env=env,
        )
    print(f"[worker] Started background worker (PID={proc.pid}), logs -> {_WORKER_LOG}")


# -- command implementations ---------------------------------------------------


def _cmd_submit(args) -> None:
    import os.path

    from eda_agent.queue.store import JobStore

    # -- Pre-flight validation ------------------------------------------------
    # Catch obvious mistakes (missing config, unknown stage) here instead of
    # letting them surface as a stack trace from the worker minutes later.
    if not os.path.isfile(args.design_config):
        print(
            f"Error: config file not found: {args.design_config}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not os.path.isabs(args.design_config):
        print(
            f"Warning: --config '{args.design_config}' is not absolute; "
            "the worker may run from a different cwd than the CLI.",
            file=sys.stderr,
        )

    if args.backend == "orfs":
        try:
            from eda_agent.backends.orfs import ORFS_STAGES
        except Exception:  # noqa: BLE001 -- backend optional
            ORFS_STAGES = None
        if ORFS_STAGES and args.stage not in ORFS_STAGES:
            valid = ", ".join(ORFS_STAGES)
            print(
                f"Error: unknown ORFS stage '{args.stage}'. Valid stages: {valid}",
                file=sys.stderr,
            )
            sys.exit(2)

    params = _parse_params(args.param)
    if args.clean:
        params["_clean"] = True
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
        current = store.get_job(args.job_id)
        status = current.status.value if current is not None else "unknown"
        print(
            f"\nStopped following logs; job is still {status}. Use 'eda-agent status {args.job_id}' to check.",
            file=sys.stderr,
        )


def _cmd_wait(args) -> None:
    """Block until a job reaches a terminal state.

    Exit code:
        0 — job succeeded
        1 — job not found, failed, or cancelled
        2 — timeout reached before terminal state
    """
    import time

    from eda_agent.queue.store import JobStatus, JobStore

    store = JobStore()
    job = store.get_job(args.job_id)
    if job is None:
        print(f"Error: job '{args.job_id}' not found.", file=sys.stderr)
        sys.exit(1)

    terminal = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED}
    deadline = (time.monotonic() + args.timeout) if args.timeout else None
    last_status = None

    try:
        while True:
            job = store.get_job(args.job_id)
            if job is None:
                print(f"Error: job '{args.job_id}' disappeared.", file=sys.stderr)
                sys.exit(1)
            if job.status != last_status and not args.quiet:
                print(f"[{job.job_id}] status: {job.status.value}")
                last_status = job.status
            if job.status in terminal:
                break
            if deadline is not None and time.monotonic() >= deadline:
                if not args.quiet:
                    print(
                        f"Timeout after {args.timeout:g}s; job still {job.status.value}.",
                        file=sys.stderr,
                    )
                sys.exit(2)
            time.sleep(max(0.1, args.interval))
    except KeyboardInterrupt:
        if not args.quiet:
            print("\nInterrupted; job continues running in background.", file=sys.stderr)
        sys.exit(130)

    if job.status == JobStatus.SUCCESS:
        sys.exit(0)
    # failed / cancelled
    if job.error_message and not args.quiet:
        print(f"Error: {job.error_message}", file=sys.stderr)
    sys.exit(1)


def _cmd_cancel(args) -> None:
    from eda_agent.queue.store import JobStatus, JobStore

    store = JobStore()

    cancel_all = bool(args.all or (args.job_id and args.job_id.lower() == "all"))

    if cancel_all:
        pending_jobs = store.list_jobs(status=JobStatus.PENDING)
        if not pending_jobs:
            print("No pending jobs to cancel.")
            return

        cancelled = 0
        for job in pending_jobs:
            if store.cancel_job(job.job_id):
                cancelled += 1

        print(f"Cancelled {cancelled}/{len(pending_jobs)} pending job(s).")
        return

    if not args.job_id:
        print("Error: job_id is required unless --all is used.", file=sys.stderr)
        sys.exit(1)

    ok = store.cancel_job(args.job_id)
    if ok:
        print(f"Job {args.job_id} cancelled.")
        return

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


def _cmd_doctor(_args) -> None:
    """Run diagnostic checks and exit with a non-zero status on failure."""
    from eda_agent import diagnostics

    results = diagnostics.run_checks()
    print(diagnostics.render_report(results, stream=sys.stdout))
    if diagnostics.worst_status(results) == diagnostics.FAIL:
        sys.exit(1)


def main() -> None:
    """Primary entry point -- dispatches to subcommand or interactive REPL."""
    parser = _build_parser()
    args = parser.parse_args()

    # No subcommand: enter the interactive REPL (with optional --session flags).
    if args.command is None:
        cli_repl(
            session_id=args.session,
            new=args.new,
            resume=args.resume,
            no_persist=args.no_persist,
            verbose=args.verbose,
            quiet=args.quiet,
            stream=args.stream,
        )
        return

    dispatch = {
        "submit": _cmd_submit,
        "list": _cmd_list,
        "status": _cmd_status,
        "logs": _cmd_logs,
        "cancel": _cmd_cancel,
        "doctor": _cmd_doctor,
        "wait": _cmd_wait,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)
