"""Small console helpers for the interactive CLI.

This module intentionally has **no third-party dependency** (no ``rich``,
no ``click``).  The goal is to provide:

* TTY-aware ANSI colour helpers.
* A ``Console`` wrapper that funnels all user-facing output through one
  place so behaviour (colour, quiet mode, spinner coordination) stays
  consistent.
* A ``Spinner`` context manager that prints a small "thinking" indicator
  on a background thread while the agent is busy, and silently degrades
  to a no-op on non-TTY streams.

Used by :mod:`eda_agent.cli` to surface ReAct progress that was
previously invisible.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import IO, Any

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_ANSI = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "grey": "\x1b[90m",
}


def _colour_enabled(stream: IO[str]) -> bool:
    """Return True iff *stream* looks like a colour-capable terminal."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("EDA_AGENT_NO_COLOR"):
        return False
    try:
        return bool(getattr(stream, "isatty", lambda: False)())
    except Exception:
        return False


def style(text: str, *names: str, stream: IO[str] | None = None) -> str:
    """Wrap *text* with the requested ANSI styles if the stream is a TTY."""
    stream = stream or sys.stdout
    if not _colour_enabled(stream):
        return text
    prefix = "".join(_ANSI[n] for n in names if n in _ANSI)
    if not prefix:
        return text
    return f"{prefix}{text}{_ANSI['reset']}"


# ---------------------------------------------------------------------------
# Truncation utility
# ---------------------------------------------------------------------------


def truncate(value: Any, limit: int = 200) -> str:
    """Coerce *value* to ``str`` and clip it to *limit* characters."""
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return text


# ---------------------------------------------------------------------------
# Console wrapper
# ---------------------------------------------------------------------------


class Console:
    """Centralised user-facing output helper.

    Parameters
    ----------
    stream:
        Output stream (default :data:`sys.stdout`).
    err_stream:
        Error stream (default :data:`sys.stderr`).
    quiet:
        When True, only :meth:`agent` and :meth:`error` write anything;
        progress / info / event lines are suppressed.  Useful for piping
        the REPL output to another tool.
    show_events:
        When True (default), step-by-step ReAct events are printed.  Set
        to False in ``--quiet`` mode.
    """

    def __init__(
        self,
        stream: IO[str] | None = None,
        err_stream: IO[str] | None = None,
        *,
        quiet: bool = False,
        show_events: bool = True,
    ) -> None:
        self.stream = stream or sys.stdout
        self.err_stream = err_stream or sys.stderr
        self.quiet = quiet
        self.show_events = show_events and not quiet
        self._lock = threading.Lock()
        # The currently-attached spinner (if any) so events can pause it
        # before printing and resume it afterwards.
        self._spinner: "Spinner | None" = None
        # Whether we're in the middle of streaming the final reply.
        self._streaming_started: bool = False

    # -- low-level ---------------------------------------------------------

    def _write(self, text: str, *, err: bool = False, end: str = "\n") -> None:
        target = self.err_stream if err else self.stream
        # Pause the spinner so it doesn't overwrite our line.
        spinner = self._spinner
        with self._lock:
            if spinner is not None:
                spinner._clear_line()
            target.write(text + end)
            try:
                target.flush()
            except Exception:
                pass
            if spinner is not None and spinner.is_running():
                spinner._render_now()

    # -- public surface ----------------------------------------------------

    def banner(self, text: str) -> None:
        self._write(text, end="")

    def info(self, text: str) -> None:
        if self.quiet:
            return
        self._write(text)

    def error(self, text: str) -> None:
        self._write(style(f"✗ Error: {text}", "red", stream=self.err_stream), err=True)

    def agent(self, text: str) -> None:
        """Print the final assistant reply.

        If a streamed response was already printed via ``token`` events,
        this just terminates the line with a blank trailing line instead
        of re-printing the full text.
        """
        if self._streaming_started:
            with self._lock:
                self.stream.write("\n\n")
                try:
                    self.stream.flush()
                except Exception:
                    pass
                self._streaming_started = False
            return
        prefix = style("■ Agent:", "bold", "green")
        # Preserve the trailing blank line the previous implementation used.
        self._write(f"\n{prefix} {text}\n", end="")

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        """Render a ReAct progress event.

        Recognised *kind* values:

        ``iteration_start``
            ``{"iteration": int}``
        ``tool_call``
            ``{"name": str, "arguments": dict}``
        ``tool_result``
            ``{"name": str, "ok": bool, "preview": str, "duration": float}``
        ``async_submission``
            ``{"job_id": str, ...}`` — printed as a hint after the reply.
        ``trace``
            ``{"name": str, "project": str, "timestamp": str}`` — only in
            verbose mode.
        ``token``
            ``{"content": str}`` — streamed token of the final reply.
            Printed inline (no newline, no styling) so the user sees the
            answer materialise progressively.
        """
        if kind == "tool_call":
            name = payload.get("name", "tool")
            self.update_spinner_text(f"running {name}")
        elif kind in {"tool_result", "async_submission"}:
            self.update_spinner_text("thinking")

        if kind == "token":
            # Always honour streaming tokens, even in --quiet mode, so the
            # final answer still reaches stdout.  The spinner is paused
            # for the first token and never re-armed (the reply is being
            # actively printed at that point).
            content = payload.get("content") or ""
            if not content:
                return
            spinner = self._spinner
            with self._lock:
                if not self._streaming_started:
                    if spinner is not None:
                        spinner._clear_line()
                        # Detach to prevent further redraws during stream.
                        self._spinner = None
                    prefix = style("\n■ Agent: ", "bold", "green", stream=self.stream)
                    self.stream.write(prefix)
                    self._streaming_started = True
                self.stream.write(content)
                try:
                    self.stream.flush()
                except Exception:
                    pass
            return
        if not self.show_events:
            return
        if kind == "iteration_start":
            iteration = payload.get("iteration", "?")
            line = style(f"▸ iteration {iteration}", "cyan")
            self._write(line)
        elif kind == "tool_call":
            name = payload.get("name", "?")
            args = payload.get("arguments") or {}
            args_preview = truncate(args, 160)
            line = (
                style("  ↪ tool: ", "blue")
                + style(name, "bold")
                + style(f"({args_preview})", "dim")
            )
            self._write(line)
        elif kind == "tool_result":
            ok = bool(payload.get("ok", True))
            dur = payload.get("duration")
            dur_str = f" ({dur:.1f}s)" if isinstance(dur, (int, float)) else ""
            mark = style("←", "green" if ok else "red")
            status = style("ok" if ok else "err", "green" if ok else "red")
            preview = truncate(payload.get("preview", ""), 200)
            preview_part = style(f"  {preview}", "dim") if preview else ""
            self._write(f"  {mark} {status}{dur_str}{preview_part}")
        elif kind == "async_submission":
            job_id = payload.get("job_id")
            if job_id:
                tip = (
                    "Tip: follow live logs with "
                    + style(f"`eda-agent logs {job_id} --follow`", "bold")
                )
                self._write(style(f"  → {tip}", "yellow"))
        elif kind == "trace":
            name = payload.get("name", "trace")
            project = payload.get("project", "")
            ts = payload.get("timestamp", "")
            line = style(
                f"  [trace] {name} project={project} ts={ts}",
                "grey",
            )
            self._write(line)
        else:
            # Unknown event – best-effort dump for debugging.
            self._write(style(f"  · {kind}: {truncate(payload, 200)}", "dim"))

    # -- spinner coordination ---------------------------------------------

    def attach_spinner(self, spinner: "Spinner | None") -> None:
        self._spinner = spinner

    def update_spinner_text(self, text: str) -> None:
        spinner = self._spinner
        if spinner is None:
            return
        spinner.set_text(text)


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------


class Spinner:
    """Tiny background spinner for long-running operations.

    Usage::

        with Spinner(console, text="thinking"):
            do_work()

    Silently no-ops when ``stream`` is not a TTY.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(
        self,
        console: Console,
        text: str = "thinking",
        stream: IO[str] | None = None,
        interval: float = 0.1,
    ) -> None:
        self._console = console
        self._text = text
        self._stream = stream or console.stream
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = self._is_tty()
        self._start_time: float = 0.0
        self._last_len: int = 0

    def _is_tty(self) -> bool:
        try:
            return bool(getattr(self._stream, "isatty", lambda: False)())
        except Exception:
            return False

    def set_text(self, text: str) -> None:
        self._text = text

    # -- internal ---------------------------------------------------------

    def _clear_line(self) -> None:
        if not self._enabled or self._last_len == 0:
            return
        try:
            self._stream.write("\r" + " " * self._last_len + "\r")
            self._stream.flush()
        except Exception:
            pass
        self._last_len = 0

    def _render_now(self) -> None:
        if not self._enabled or self._stop.is_set():
            return
        elapsed = time.monotonic() - self._start_time
        frame_idx = int(elapsed / self._interval) % len(self._FRAMES)
        frame = self._FRAMES[frame_idx]
        line = style(
            f"{frame} {self._text} ({elapsed:0.1f}s)", "cyan", stream=self._stream
        )
        # Always pad to at least previous length so leftovers are erased.
        try:
            self._stream.write("\r" + line)
            self._stream.flush()
        except Exception:
            pass
        # Strip ANSI to compute visible length for clearing later.
        visible = f"{frame} {self._text} ({elapsed:0.1f}s)"
        self._last_len = max(self._last_len, len(visible))

    def _run(self) -> None:
        self._start_time = time.monotonic()
        while not self._stop.wait(self._interval):
            # Console may print events concurrently; the console lock
            # serialises access for us.
            with self._console._lock:
                if self._stop.is_set():
                    break
                self._render_now()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- context manager --------------------------------------------------

    def __enter__(self) -> "Spinner":
        if not self._enabled:
            return self
        self._console.attach_spinner(self)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        with self._console._lock:
            self._clear_line()
        self._console.attach_spinner(None)
