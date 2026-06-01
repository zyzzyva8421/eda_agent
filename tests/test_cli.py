"""Tests for the CLI REPL module."""

from __future__ import annotations

import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from eda_agent.cli import (
    _build_prompt,
    _complete_cmd_name,
    _format_repl_error,
    _parse_slash_command,
    _path_completions,
    cli_repl,
)


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
    out, _ = _run_cli_with_input(["/help", "exit"])
    assert "/clear" in out
    assert "/history" in out
    assert "/cd" in out
    assert "!" in out


def test_clear_command():
    out, _ = _run_cli_with_input(["/clear", "exit"])
    assert "cleared" in out.lower()


def test_history_empty_session():
    out, _ = _run_cli_with_input(["/history", "exit"])
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


def test_unexpected_exception_does_not_crash_repl():
    """Even exceptions outside the legacy narrow tuple must not kill the REPL."""
    with patch("eda_agent.cli.Planner") as MockPlanner:
        instance = MockPlanner.return_value
        # KeyError used to bubble out of cli_repl in the previous narrow except.
        instance.run.side_effect = KeyError("missing_field")
        out, err = _run_cli_with_input(["check timing", "exit"])
    combined = out + err
    # The REPL must have reached "Goodbye" — proving it survived the KeyError.
    assert "Goodbye" in out
    assert "KeyError" in combined or "missing_field" in combined


def test_forget_requires_confirmation():
    """`/forget` without 'yes' must not wipe the session."""
    with patch("eda_agent.cli.clear_session") as mock_clear:
        # User types '/forget', then declines confirmation, then exits.
        out, _ = _run_cli_with_input(["/forget", "no", "exit"])
    mock_clear.assert_not_called()
    assert "cancelled" in out.lower()


def test_forget_with_yes_wipes_session():
    with patch("eda_agent.cli.clear_session") as mock_clear:
        out, _ = _run_cli_with_input(["/forget", "yes", "exit"])
    mock_clear.assert_called_once()
    assert "wiped" in out.lower()


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
    """'/cd <dir>' should change the working directory."""
    original = os.getcwd()
    try:
        out, err = _run_cli_with_input([f"/cd {tmp_path}", "exit"])
        assert str(tmp_path) in out or os.getcwd() == str(tmp_path)
    finally:
        os.chdir(original)


def test_cd_invalid_dir():
    """'/cd' to a non-existent path should print an error and not crash."""
    out, err = _run_cli_with_input(["/cd /nonexistent_path_xyz_abc", "exit"])
    assert "Goodbye" in out
    assert "cd:" in err


def test_cd_no_args(tmp_path, monkeypatch):
    """'/cd' with no argument should change to $HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    original = os.getcwd()
    try:
        out, err = _run_cli_with_input(["/cd", "exit"])
        assert str(tmp_path) in out
    finally:
        os.chdir(original)


def test_natural_language_help_is_forwarded_to_agent():
    with patch("eda_agent.cli.Planner") as MockPlanner:
        instance = MockPlanner.return_value
        instance.run.return_value = "done"
        _run_cli_with_input(["help me with synth", "exit"])
    instance.run.assert_called_once()
    assert instance.run.call_args.args[0] == "help me with synth"


def test_multiline_input_is_forwarded_as_single_turn():
    with patch("eda_agent.cli.Planner") as MockPlanner:
        instance = MockPlanner.return_value
        instance.run.return_value = "ok"
        _run_cli_with_input(['"""', "line 1", "line 2", '"""', "exit"])
    instance.run.assert_called_once()
    assert instance.run.call_args.args[0] == "line 1\nline 2"


def test_shell_cd_prints_builtin_hint():
    out, err = _run_cli_with_input(["!cd /tmp", "exit"])
    assert "built-in '/cd'" in err
    assert "Goodbye" in out


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_complete_cmd_name_returns_executables():
    results = _complete_cmd_name("ls")
    # 'ls' should be found on any POSIX system in PATH
    assert any(r.startswith("ls") for r in results)


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


def test_parse_slash_command():
    assert _parse_slash_command("/history --full") == ("history", "--full")
    assert _parse_slash_command("plain text") is None


def test_build_prompt_includes_session_context_and_cwd(tmp_path, monkeypatch):
    from eda_agent.agent.memory import AgentMemory

    monkeypatch.chdir(tmp_path)
    memory = AgentMemory()
    memory.set("design_name", "aes")
    memory.set("pdk", "sky130hd")
    prompt = _build_prompt(memory, "demo")
    assert "demo" in prompt
    assert "aes@sky130hd" in prompt
    assert tmp_path.name in prompt


def test_format_repl_error_adds_suggestion():
    text = _format_repl_error(ConnectionError("connection refused"), verbose=0)
    assert "Connection failed" in text
    assert "-vv" in text


# ---------------------------------------------------------------------------
# `submit` subcommand pre-flight validation
# ---------------------------------------------------------------------------


def _submit_args(**overrides):
    """Build a minimal argparse.Namespace for _cmd_submit."""
    from types import SimpleNamespace

    base = {
        "backend": "orfs",
        "stage": "synth",
        "design_name": "gcd",
        "design_config": "/nonexistent/path/config.mk",
        "pdk": "sky130hd",
        "param": [],
        "clean": False,
        "no_worker": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cmd_submit_rejects_missing_config(tmp_path, capsys):
    from eda_agent.cli import _cmd_submit

    args = _submit_args(design_config=str(tmp_path / "missing.mk"))
    try:
        _cmd_submit(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit(2) for missing config")
    err = capsys.readouterr().err
    assert "config file not found" in err.lower()


def test_cmd_submit_rejects_unknown_orfs_stage(tmp_path, capsys):
    from eda_agent.cli import _cmd_submit

    cfg = tmp_path / "config.mk"
    cfg.write_text("DESIGN_NAME=gcd\n")
    args = _submit_args(design_config=str(cfg), stage="not_a_stage")
    try:
        _cmd_submit(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit(2) for unknown stage")
    err = capsys.readouterr().err
    assert "unknown orfs stage" in err.lower()
    assert "synth" in err  # the valid-list is included


def test_cmd_submit_warns_on_relative_config(tmp_path, capsys, monkeypatch):
    from eda_agent.cli import _cmd_submit

    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config.mk"
    cfg.write_text("DESIGN_NAME=gcd\n")

    fake_job = type(
        "J",
        (),
        {
            "job_id": "abc",
            "backend": "orfs",
            "stage": "synth",
            "design_name": "gcd",
            "pdk": "sky130hd",
            "design_config": "config.mk",
            "status": type("S", (), {"value": "pending"})(),
        },
    )()

    with patch("eda_agent.queue.store.JobStore") as MockStore:
        MockStore.return_value.create_job.return_value = fake_job
        args = _submit_args(design_config="config.mk")  # relative
        _cmd_submit(args)
    err = capsys.readouterr().err
    assert "not absolute" in err.lower()


# ---------------------------------------------------------------------------
# `wait` subcommand
# ---------------------------------------------------------------------------


def _wait_args(**overrides):
    from types import SimpleNamespace

    base = {
        "job_id": "abc",
        "timeout": None,
        "interval": 0.0,
        "quiet": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _fake_job(status_value, error_message=None):
    from eda_agent.queue.store import JobStatus

    job = type("J", (), {})()
    job.job_id = "abc"
    job.status = JobStatus(status_value)
    job.error_message = error_message
    return job


def test_cmd_wait_exits_zero_on_success():
    from eda_agent.cli import _cmd_wait

    states = iter([_fake_job("pending"), _fake_job("running"), _fake_job("success")])
    with patch("eda_agent.queue.store.JobStore") as MockStore:
        MockStore.return_value.get_job.side_effect = lambda _jid: next(states)
        try:
            _cmd_wait(_wait_args())
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("expected SystemExit(0)")


def test_cmd_wait_exits_nonzero_on_failure(capsys):
    from eda_agent.cli import _cmd_wait

    states = iter([_fake_job("running"), _fake_job("failed", error_message="boom")])
    with patch("eda_agent.queue.store.JobStore") as MockStore:
        MockStore.return_value.get_job.side_effect = lambda _jid: next(states)
        try:
            _cmd_wait(_wait_args(quiet=False))
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit(1)")
    err = capsys.readouterr().err
    assert "boom" in err


def test_cmd_wait_exits_one_when_job_not_found():
    from eda_agent.cli import _cmd_wait

    with patch("eda_agent.queue.store.JobStore") as MockStore:
        MockStore.return_value.get_job.return_value = None
        try:
            _cmd_wait(_wait_args())
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit(1)")


def test_cmd_wait_timeout_returns_two():
    from eda_agent.cli import _cmd_wait

    with patch("eda_agent.queue.store.JobStore") as MockStore:
        # Always pending → never reaches terminal
        MockStore.return_value.get_job.return_value = _fake_job("pending")
        try:
            _cmd_wait(_wait_args(timeout=0.05, interval=0.01))
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("expected SystemExit(2) on timeout")


def test_cmd_logs_follow_ctrl_c_prints_status_hint(tmp_path, capsys):
    from eda_agent.cli import _cmd_logs
    from eda_agent.queue.store import JobStatus

    log_path = tmp_path / "job.log"
    log_path.write_text("")
    job = SimpleNamespace(job_id="abc", log_path=str(log_path), status=JobStatus.RUNNING)

    class _BoomFile:
        def __enter__(self):
            raise KeyboardInterrupt

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("eda_agent.queue.store.JobStore") as MockStore:
        MockStore.return_value.get_job.side_effect = [job, job]
        with patch("pathlib.Path.open", return_value=_BoomFile()):
            _cmd_logs(SimpleNamespace(job_id="abc", follow=True))
    err = capsys.readouterr().err
    assert "Stopped following logs" in err
    assert "eda-agent status abc" in err


# ---------------------------------------------------------------------------
# `--version` flag
# ---------------------------------------------------------------------------


def test_version_flag_prints_version_and_exits(capsys):
    from eda_agent.cli import main

    with patch.object(sys, "argv", ["eda-agent", "--version"]):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("expected SystemExit(0) from --version")
    out = capsys.readouterr().out
    assert "eda-agent" in out
    # Version should be either the real installed version or "unknown".
    assert any(token in out for token in (".", "unknown"))


def test_short_version_flag_works(capsys):
    from eda_agent.cli import main

    with patch.object(sys, "argv", ["eda-agent", "-V"]):
        try:
            main()
        except SystemExit as exc:
            assert exc.code == 0
    out = capsys.readouterr().out
    assert "eda-agent" in out
