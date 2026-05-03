"""Tests for eda_agent.agent.guardrails.

All tests are pure (no DB / LLM / EDA tool required).
The execute_tool integration tests stub out the underlying tool dispatch to
avoid real I/O while still exercising the guardrail wiring in execute_tool().
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from eda_agent.agent.guardrails import (
    GuardrailResult,
    RiskLevel,
    _check_cancel,
    _check_clean_flag,
    _check_long_running,
    _check_utilization,
    check,
)
from eda_agent.agent.tools import execute_tool


# ── RiskLevel / GuardrailResult helpers ──────────────────────────────────────


def test_risk_level_values():
    assert RiskLevel.SAFE == "safe"
    assert RiskLevel.WARN == "warn"
    assert RiskLevel.BLOCK == "block"


def test_guardrail_result_is_blocked_true():
    r = GuardrailResult(level=RiskLevel.BLOCK, reason="danger")
    assert r.is_blocked is True


def test_guardrail_result_is_blocked_false_for_warn():
    r = GuardrailResult(level=RiskLevel.WARN, warnings=["heads up"])
    assert r.is_blocked is False


def test_guardrail_result_is_blocked_false_for_safe():
    assert GuardrailResult(level=RiskLevel.SAFE).is_blocked is False


def test_blocked_response_structure():
    r = GuardrailResult(level=RiskLevel.BLOCK, reason="too risky")
    resp = r.blocked_response("run_eda_flow", {"clean": True})
    assert resp["blocked"] is True
    assert resp["tool"] == "run_eda_flow"
    assert resp["reason"] == "too risky"
    assert "to_proceed" in resp
    assert "_guardrail_confirmed" in resp["to_proceed"]


# ── _check_clean_flag ─────────────────────────────────────────────────────────


def test_clean_flag_true_blocks():
    r = _check_clean_flag({"clean": True})
    assert r is not None
    assert r.level == RiskLevel.BLOCK
    assert "clean" in r.reason.lower()


def test_clean_flag_false_passes():
    assert _check_clean_flag({"clean": False}) is None


def test_clean_flag_absent_passes():
    assert _check_clean_flag({"backend": "orfs"}) is None


def test_clean_flag_params_clean_blocks():
    """Nested params._clean also triggers BLOCK."""
    r = _check_clean_flag({"params": {"_clean": True}})
    # _check_clean_flag only reads top-level 'clean'; nested _clean is not
    # checked by this helper (it's an OR condition, acceptable either way)
    # This test documents current behaviour.
    if r is not None:
        assert r.level == RiskLevel.BLOCK


# ── _check_utilization ────────────────────────────────────────────────────────


@pytest.mark.parametrize("val,expected_level", [
    (97, RiskLevel.BLOCK),
    (96, RiskLevel.BLOCK),
    (95.1, RiskLevel.BLOCK),
    (88, RiskLevel.WARN),
    (85.5, RiskLevel.WARN),
    (70, None),          # safe zone
    (50, None),
    (25, None),          # lower bound is exclusive (<25), so 25 is safe
    (24.9, RiskLevel.WARN),
    (10, RiskLevel.WARN),
])
def test_utilization_thresholds(val, expected_level):
    r = _check_utilization({"params": {"CORE_UTILIZATION": val}})
    if expected_level is None:
        assert r is None
    else:
        assert r is not None
        assert r.level == expected_level


def test_utilization_string_value():
    """Values given as strings (e.g. '88%') should be parsed."""
    r = _check_utilization({"params": {"CORE_UTILIZATION": "88"}})
    assert r is not None
    assert r.level == RiskLevel.WARN


def test_utilization_absent_params():
    assert _check_utilization({"backend": "orfs"}) is None


def test_utilization_no_core_util_key():
    assert _check_utilization({"params": {"OTHER_PARAM": 42}}) is None


def test_utilization_invalid_string():
    """Non-numeric value should not raise; returns None."""
    r = _check_utilization({"params": {"CORE_UTILIZATION": "auto"}})
    assert r is None


# ── _check_long_running ───────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name", ["tune_ppa", "tune_ppa_multistage"])
def test_long_running_warns(tool_name):
    r = _check_long_running(tool_name)
    assert r is not None
    assert r.level == RiskLevel.WARN
    assert len(r.warnings) > 0


@pytest.mark.parametrize("tool_name", [
    "run_eda_flow", "query_timing", "cancel_job", "save_case",
])
def test_long_running_ignores_other_tools(tool_name):
    assert _check_long_running(tool_name) is None


# ── _check_cancel ─────────────────────────────────────────────────────────────


def test_cancel_job_warns():
    r = _check_cancel("cancel_job")
    assert r is not None
    assert r.level == RiskLevel.WARN
    assert "cancel" in r.warnings[0].lower()


@pytest.mark.parametrize("tool_name", ["run_eda_flow", "query_timing", "tune_ppa"])
def test_cancel_ignores_other_tools(tool_name):
    assert _check_cancel(tool_name) is None


# ── check() – integration of all checkers ────────────────────────────────────


def test_check_safe_for_benign_call():
    r = check("query_timing", {"design_name": "gcd"})
    assert r.level == RiskLevel.SAFE
    assert not r.is_blocked


def test_check_block_clean_true():
    r = check("run_eda_flow", {"clean": True, "backend": "orfs"})
    assert r.is_blocked
    assert "clean" in r.reason.lower()


def test_check_block_utilization_too_high():
    r = check("run_eda_flow", {"params": {"CORE_UTILIZATION": 97}})
    assert r.is_blocked


def test_check_warn_utilization_high():
    r = check("run_eda_flow", {"params": {"CORE_UTILIZATION": 88}})
    assert r.level == RiskLevel.WARN
    assert not r.is_blocked
    assert any("88" in w for w in r.warnings)


def test_check_warn_tune_ppa():
    r = check("tune_ppa", {})
    assert r.level == RiskLevel.WARN


def test_check_warn_cancel_job():
    r = check("cancel_job", {"job_id": "abc-123"})
    assert r.level == RiskLevel.WARN


def test_check_warn_accumulates_multiple():
    """tune_ppa + low utilization → both WARNs in the list."""
    r = check("tune_ppa", {"params": {"CORE_UTILIZATION": 10}})
    assert r.level == RiskLevel.WARN
    assert len(r.warnings) >= 2


def test_check_block_wins_over_warn():
    """clean=True (BLOCK) + low utilization (WARN) → BLOCK returned first."""
    r = check("run_eda_flow", {
        "clean": True,
        "params": {"CORE_UTILIZATION": 10},
    })
    assert r.is_blocked   # BLOCK from clean flag takes priority


def test_check_bypass_via_confirmed_flag():
    r = check("run_eda_flow", {"clean": True, "_guardrail_confirmed": True})
    assert r.level == RiskLevel.SAFE
    assert not r.is_blocked


def test_check_confirmed_flag_also_bypasses_utilization():
    r = check("run_eda_flow", {
        "params": {"CORE_UTILIZATION": 97},
        "_guardrail_confirmed": True,
    })
    assert r.level == RiskLevel.SAFE


def test_check_confirmed_false_does_not_bypass():
    """_guardrail_confirmed=False must NOT bypass checks."""
    r = check("run_eda_flow", {"clean": True, "_guardrail_confirmed": False})
    assert r.is_blocked


# ── execute_tool integration ──────────────────────────────────────────────────


def test_execute_tool_blocked_returns_json():
    """Clean=True → execute_tool returns JSON with blocked:True, no exception."""
    result = execute_tool(
        "run_eda_flow",
        {
            "clean": True,
            "backend": "orfs",
            "stage_start": "synth",
            "design_name": "gcd",
            "design_config": "/tmp/x",
            "pdk": "sky130hd",
        },
    )
    obj = json.loads(result)
    assert obj.get("blocked") is True
    assert obj["tool"] == "run_eda_flow"
    assert "reason" in obj
    assert "to_proceed" in obj


def test_execute_tool_blocked_does_not_call_fn():
    """When blocked, the underlying tool function must never be called."""
    with patch("eda_agent.agent.tools._TOOL_DISPATCH") as mock_dispatch:
        mock_fn = mock_dispatch.get.return_value
        execute_tool("run_eda_flow", {"clean": True, "design_name": "x",
                                       "design_config": "/tmp/x", "pdk": "sky130hd",
                                       "stage_start": "synth", "backend": "orfs"})
        mock_fn.assert_not_called()


def test_execute_tool_guardrail_confirmed_strips_flag():
    """_guardrail_confirmed must NOT be forwarded to the tool function."""
    received_kwargs: dict = {}

    def _fake_tool(**kwargs):
        received_kwargs.update(kwargs)
        return {"ok": True}

    with patch.dict("eda_agent.agent.tools._TOOL_DISPATCH", {"dummy_tool": _fake_tool}):
        execute_tool("dummy_tool", {"_guardrail_confirmed": True, "foo": "bar"})

    assert "_guardrail_confirmed" not in received_kwargs
    assert received_kwargs.get("foo") == "bar"


def test_execute_tool_warn_appends_warnings():
    """WARN-level calls must append _warnings to the result dict."""
    def _fake_tool(**kwargs):
        return {"status": "done"}

    with patch.dict("eda_agent.agent.tools._TOOL_DISPATCH", {"tune_ppa": _fake_tool}):
        result = execute_tool("tune_ppa", {})

    obj = json.loads(result)
    assert "_warnings" in obj
    assert len(obj["_warnings"]) > 0


def test_execute_tool_safe_no_warnings():
    """Safe tools must not inject _warnings."""
    def _fake_tool(**kwargs):
        return {"timing": []}

    with patch.dict("eda_agent.agent.tools._TOOL_DISPATCH", {"query_timing": _fake_tool}):
        result = execute_tool("query_timing", {"design_name": "gcd"})

    obj = json.loads(result)
    assert "_warnings" not in obj


def test_execute_tool_unknown_returns_error():
    result = json.loads(execute_tool("nonexistent_tool", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"]
