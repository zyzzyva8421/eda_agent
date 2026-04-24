"""Tests for the CLI REPL module."""

from __future__ import annotations

import io
from unittest.mock import patch

from eda_agent.cli import cli_repl


def _run_cli_with_input(inputs: list[str]) -> str:
    """Run the REPL with the given sequence of inputs and return stdout."""
    input_iter = iter(inputs)

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(input_iter)
        except StopIteration:
            raise EOFError

    captured = io.StringIO()
    with patch("builtins.input", side_effect=fake_input):
        with patch("sys.stdout", captured):
            cli_repl()
    return captured.getvalue()


def test_exit_command():
    out = _run_cli_with_input(["exit"])
    assert "Goodbye" in out


def test_quit_command():
    out = _run_cli_with_input(["quit"])
    assert "Goodbye" in out


def test_eof_exits_gracefully():
    out = _run_cli_with_input([])  # immediately raises EOFError
    assert "Goodbye" in out


def test_help_command():
    out = _run_cli_with_input(["help", "exit"])
    assert "clear" in out
    assert "history" in out


def test_clear_command():
    out = _run_cli_with_input(["clear", "exit"])
    assert "cleared" in out.lower()


def test_history_empty_session():
    out = _run_cli_with_input(["history", "exit"])
    assert "empty" in out.lower()


def test_agent_error_does_not_crash():
    """If the planner raises an exception the REPL should print an error and continue."""
    with patch("eda_agent.cli.Planner") as MockPlanner:
        instance = MockPlanner.return_value
        instance.run.side_effect = RuntimeError("LLM unavailable")
        # Capture both stdout and stderr
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        with patch("builtins.input", side_effect=iter(["check timing for gcd", "exit"])):
            with patch("sys.stdout", captured_out):
                with patch("sys.stderr", captured_err):
                    cli_repl()
        combined = captured_out.getvalue() + captured_err.getvalue()
        # Should not raise; should print an error message and continue
        assert "Error" in combined or "error" in combined.lower()
