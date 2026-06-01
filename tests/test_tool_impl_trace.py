"""Tests for PostgreSQL compatibility paths in tool_impl_trace helpers."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from eda_agent.agent.tool_impl_trace import latest_inference_context_for_run_impl


def test_latest_inference_context_uses_jsonb_operator_when_supported():
    db = MagicMock()
    session_ctx_result = MagicMock()
    session_ctx_result.first.return_value = None
    inf_result = MagicMock()
    inf_result.mappings.return_value.first.return_value = {
        "id": 12,
        "chosen_cause": "rule.alpha",
        "hypotheses": [],
    }
    case_result = MagicMock()
    case_result.first.return_value = (34,)
    db.execute.side_effect = [session_ctx_result, inf_result, case_result]

    with patch("eda_agent.agent.tool_impl_trace.supports_postgresql_jsonb", return_value=True):
        result = latest_inference_context_for_run_impl(7, get_db_fn=lambda: nullcontext(db))

    assert result == {"inference_id": 12, "case_id": 34, "rule_id": "rule.alpha"}
    query = str(db.execute.call_args_list[2].args[0])
    assert "result_metrics->>'inference_id'" in query
    assert db.execute.call_args_list[2].args[1] == {"inference_id": "12"}


def test_latest_inference_context_falls_back_without_jsonb_support():
    db = MagicMock()
    session_ctx_result = MagicMock()
    session_ctx_result.first.return_value = None
    inf_result = MagicMock()
    inf_result.mappings.return_value.first.return_value = {
        "id": 12,
        "chosen_cause": None,
        "hypotheses": [{"cause_id": "rule.beta"}],
    }
    case_result = MagicMock()
    case_result.first.return_value = (56,)
    db.execute.side_effect = [session_ctx_result, inf_result, case_result]

    with patch("eda_agent.agent.tool_impl_trace.supports_postgresql_jsonb", return_value=False):
        result = latest_inference_context_for_run_impl(7, get_db_fn=lambda: nullcontext(db))

    assert result == {"inference_id": 12, "case_id": 56, "rule_id": "rule.beta"}
    query = str(db.execute.call_args_list[2].args[0])
    params = db.execute.call_args_list[2].args[1]
    assert "REPLACE(CAST(result_metrics AS TEXT), ' ', '')" in query
    assert params == {
        "pattern_numeric": '%"inference_id":12%',
        "pattern_string": '%"inference_id":"12"%',
    }
