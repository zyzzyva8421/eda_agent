"""Tests for the CLI REPL module."""

from __future__ import annotations

import io
import os
from unittest.mock import patch

from eda_agent.cli import _complete_cmd_name, _path_completions, cli_repl


def _run_cli_with_input(inputs: list[str]) -> tuple[str, str]:
    """Run the REPL with the given sequence of inputs and return (stdout, stderr)."""
    input_iter = iter(inputs)

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(input_iter)
        except StopIteration:
            raise EOFError

    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with patch("builtins.input", side_effect=fake_input):
        with patch("sys.stdout", captured_out):
            with patch("sys.stderr", captured_err):
                cli_repl()
    return captured_out.getvalue(), captured_err.getvalue()


def test_exit_command():
    out, _ = _run_cli_with_input(["exit"])
    assert "Goodbye" in out


def test_quit_command():
    out, _ = _run_cli_with_input(["quit"])
    assert "Goodbye" in out


def test_eof_exits_gracefully():
    out, _ = _run_cli_with_input([])  # immediately raises EOFError
    assert "Goodbye" in out


def test_help_command():
    out, _ = _run_cli_with_input(["help", "exit"])
    assert "clear" in out
    assert "history" in out
    assert "cd" in out
    assert "!" in out


def test_clear_command():
    out, _ = _run_cli_with_input(["clear", "exit"])
    assert "cleared" in out.lower()


def test_history_empty_session():
    out, _ = _run_cli_with_input(["history", "exit"])
    assert "empty" in out.lower()


def test_agent_error_does_not_crash():
    """If the planner raises an exception the REPL should print an error and continue."""
    with patch("eda_agent.cli.Planner") as MockPlanner:
        instance = MockPlanner.return_value
        instance.run.side_effect = RuntimeError("LLM unavailable")
        out, err = _run_cli_with_input(["check timing for gcd", "exit"])
        combined = out + err
        # Should not raise; should print an error message and continue
        assert "Error" in combined or "error" in combined.lower()


def test_shell_command_execution():
    """!<cmd> should run the shell command and not forward it to the agent."""
    with patch("eda_agent.cli.subprocess.run") as mock_run:
        out, err = _run_cli_with_input(["!echo hello", "exit"])
        mock_run.assert_called_once_with("echo hello", shell=True)  # noqa: S604
    # Nothing forwarded to LLM; Goodbye still printed
    assert "Goodbye" in out


def test_shell_command_empty_prefix():
    """A bare '!' with no command should print a usage hint, not crash."""
    out, err = _run_cli_with_input(["!", "exit"])
    assert "Usage" in err or "usage" in err.lower()
    assert "Goodbye" in out


def test_shell_command_os_error():
    """An OSError during subprocess.run should be reported, not crash the REPL."""
    with patch("eda_agent.cli.subprocess.run", side_effect=OSError("not found")):
        out, err = _run_cli_with_input(["!nonexistent", "exit"])
    assert "Goodbye" in out
    assert "error" in (out + err).lower()


def test_cd_command(tmp_path):
    """'cd <dir>' should change the working directory."""
    original = os.getcwd()
    try:
        out, err = _run_cli_with_input([f"cd {tmp_path}", "exit"])
        assert str(tmp_path) in out or os.getcwd() == str(tmp_path)
    finally:
        os.chdir(original)


def test_cd_invalid_dir():
    """'cd' to a non-existent path should print an error and not crash."""
    out, err = _run_cli_with_input(["cd /nonexistent_path_xyz_abc", "exit"])
    assert "Goodbye" in out
    assert "cd:" in err


def test_cd_no_args(tmp_path, monkeypatch):
    """'cd' with no argument should change to $HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    original = os.getcwd()
    try:
        out, err = _run_cli_with_input(["cd", "exit"])
        assert str(tmp_path) in out
    finally:
        os.chdir(original)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_complete_cmd_name_returns_executables():
    results = _complete_cmd_name("ls")
    # 'ls' should be found on any POSIX system in PATH
    assert any(r == "ls" or r.startswith("ls") for r in results)


def test_complete_cmd_name_empty_prefix_returns_list():
    results = _complete_cmd_name("")
    assert isinstance(results, list)
    assert len(results) > 0


def test_path_completions_returns_entries(tmp_path):
    (tmp_path / "file_a.txt").write_text("a")
    (tmp_path / "file_b.txt").write_text("b")
    sub = tmp_path / "subdir"
    sub.mkdir()

    results = _path_completions(str(tmp_path) + "/")
    names = [os.path.basename(r.rstrip("/")) for r in results]
    assert "file_a.txt" in names
    assert "file_b.txt" in names
    # Directories should get a trailing slash
    assert any(r.endswith("subdir/") for r in results)


def test_path_completions_no_match():
    results = _path_completions("/nonexistent_xyz_abc_123/")
    assert results == []
