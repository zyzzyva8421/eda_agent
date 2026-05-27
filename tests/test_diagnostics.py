"""Tests for the ``eda-agent doctor`` diagnostic checks."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from eda_agent import diagnostics
from eda_agent.diagnostics import (
    FAIL,
    OK,
    WARN,
    CheckResult,
    check_env_file,
    count,
    format_result,
    render_report,
    run_checks,
    worst_status,
)

# ---------------------------------------------------------------------------
# CheckResult / helpers
# ---------------------------------------------------------------------------


def test_worst_status_picks_highest_severity():
    results = [
        CheckResult("a", OK),
        CheckResult("b", WARN),
        CheckResult("c", FAIL),
    ]
    assert worst_status(results) == FAIL


def test_worst_status_on_empty_is_ok():
    assert worst_status([]) == OK


def test_count_by_status():
    results = [
        CheckResult("a", OK),
        CheckResult("b", WARN),
        CheckResult("c", FAIL),
        CheckResult("d", FAIL),
    ]
    assert count(results, FAIL) == 2
    assert count(results, WARN) == 1
    assert count(results, OK) == 1


def test_format_result_includes_name_and_detail():
    line = format_result(CheckResult("X", OK, "everything is fine"), stream=io.StringIO())
    assert "X" in line
    assert "everything is fine" in line


def test_format_result_omits_hint_when_ok():
    line = format_result(
        CheckResult("X", OK, "fine", hint="should-not-appear"),
        stream=io.StringIO(),
    )
    assert "should-not-appear" not in line


def test_format_result_shows_hint_when_fail():
    line = format_result(
        CheckResult("X", FAIL, "broken", hint="run the fix"),
        stream=io.StringIO(),
    )
    assert "hint: run the fix" in line


# ---------------------------------------------------------------------------
# check_env_file
# ---------------------------------------------------------------------------


def test_check_env_file_found(tmp_path: Path):
    (tmp_path / ".env").write_text("MINIMAX_API_KEY=x")
    result = check_env_file(cwd=tmp_path)
    assert result.status == OK
    assert ".env" in result.detail


def test_check_env_file_only_example_present(tmp_path: Path):
    (tmp_path / ".env.example").write_text("MINIMAX_API_KEY=")
    result = check_env_file(cwd=tmp_path)
    assert result.status == WARN
    assert "cp" in result.hint


def test_check_env_file_neither_present(tmp_path: Path):
    result = check_env_file(cwd=tmp_path)
    assert result.status == WARN
    assert result.hint  # we expect a remediation hint


# ---------------------------------------------------------------------------
# run_checks / render_report
# ---------------------------------------------------------------------------


def test_run_checks_isolates_failing_check():
    def boom() -> CheckResult:  # noqa: D401
        raise RuntimeError("intentional")

    def good() -> CheckResult:
        return CheckResult("good", OK, "all fine")

    results = run_checks(checks=(boom, good))
    assert len(results) == 2
    assert results[0].status == FAIL
    assert "intentional" in results[0].detail
    assert results[1].status == OK


def test_render_report_summary_reflects_worst_status():
    results = [CheckResult("a", OK, "ok"), CheckResult("b", FAIL, "broken")]
    text = render_report(results, stream=io.StringIO())
    assert "broken" in text
    assert "blocking" in text.lower()


def test_render_report_all_ok_message():
    text = render_report([CheckResult("a", OK, "ok")], stream=io.StringIO())
    assert "passed" in text.lower()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cmd_doctor_exits_nonzero_when_failures(capsys):
    from eda_agent.cli import _cmd_doctor

    fake = [CheckResult("api", FAIL, "missing key", hint="set MINIMAX_API_KEY")]
    with patch.object(diagnostics, "run_checks", return_value=fake):
        try:
            _cmd_doctor(None)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")
    out = capsys.readouterr().out
    assert "missing key" in out
    assert "MINIMAX_API_KEY" in out


def test_cmd_doctor_exits_zero_when_all_ok(capsys):
    from eda_agent.cli import _cmd_doctor

    fake = [CheckResult("api", OK, "good"), CheckResult("db", WARN, "minor")]
    with patch.object(diagnostics, "run_checks", return_value=fake):
        # Warnings should NOT trigger a non-zero exit; doctor only fails hard
        # on FAIL so users can still proceed past best-effort warnings.
        _cmd_doctor(None)
    out = capsys.readouterr().out
    assert "minor" in out
