from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


class _Ctx:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, tb):
        return False


def test_latest_inference_context_for_run_empty():
    from eda_agent.agent.tools import _latest_inference_context_for_run

    db = MagicMock()
    exec1 = MagicMock()
    exec1.first.return_value = None
    exec2 = MagicMock()
    exec2.mappings.return_value.first.return_value = None
    db.execute.side_effect = [exec1, exec2]

    with patch("eda_agent.agent.tools.get_db", return_value=_Ctx(db)):
        ctx = _latest_inference_context_for_run(123)

    assert ctx == {"inference_id": None, "case_id": None, "rule_id": None}


def test_latest_inference_context_for_run_with_case_and_rule():
    from eda_agent.agent.tools import _latest_inference_context_for_run

    db = MagicMock()

    exec1 = MagicMock()
    exec1.first.return_value = None

    exec2 = MagicMock()
    exec2.mappings.return_value.first.return_value = {
        "id": 42,
        "chosen_cause": "routing_detour",
        "hypotheses": [{"cause_id": "routing_detour"}],
    }

    exec3 = MagicMock()
    exec3.first.return_value = (7,)

    db.execute.side_effect = [exec1, exec2, exec3]

    with patch("eda_agent.agent.tools.get_db", return_value=_Ctx(db)):
        ctx = _latest_inference_context_for_run(999)

    assert ctx["inference_id"] == 42
    assert ctx["case_id"] == 7
    assert ctx["rule_id"] == "routing_detour"


def test_latest_inference_context_prefers_flow_session_cache():
    from eda_agent.agent.tools import _latest_inference_context_for_run

    db = MagicMock()
    exec1 = MagicMock()
    exec1.first.return_value = (1001, 88, "cts_skew")
    db.execute.side_effect = [exec1]

    with patch("eda_agent.agent.tools.get_db", return_value=_Ctx(db)):
        ctx = _latest_inference_context_for_run(55)

    assert ctx == {"inference_id": 1001, "case_id": 88, "rule_id": "cts_skew"}


def test_infer_root_cause_tool_updates_flow_session_context():
    from eda_agent.agent.tools import _infer_root_cause_tool

    infer_payload = {
        "inference_id": 66,
        "hypotheses": [{"cause_id": "routing_detour"}],
    }

    with patch("eda_agent.agent.inference.engine.infer", return_value=infer_payload):
        with patch("eda_agent.agent.tools._set_flow_session_context_from_run") as mock_set:
            out = _infer_root_cause_tool(run_id=123, symptoms="wns bad")

    assert out["inference_id"] == 66
    mock_set.assert_called_once_with(
        123,
        inference_id=66,
        rule_id="routing_detour",
    )


def test_confirm_root_cause_tool_updates_flow_session_context():
    from eda_agent.agent.tools import _confirm_root_cause_tool

    db = MagicMock()
    exec1 = MagicMock()
    exec1.first.return_value = (321,)
    db.execute.side_effect = [exec1]

    with patch(
        "eda_agent.agent.inference.engine.confirm",
        return_value={"status": "confirmed", "case_id": 7},
    ):
        with patch("eda_agent.agent.tools.get_db", return_value=_Ctx(db)):
            with patch("eda_agent.agent.tools._set_flow_session_context_from_run") as mock_set:
                out = _confirm_root_cause_tool(
                    inference_id=91,
                    confirmed_cause_id="routing_detour",
                )

    assert out["status"] == "confirmed"
    mock_set.assert_called_once_with(
        321,
        inference_id=91,
        case_id=7,
        rule_id="routing_detour",
    )


def test_decision_reason_structured_from_suggestion():
    from eda_agent.agent.tools import _decision_reason_structured_from_suggestion

    suggestion = {
        "reasoning": ["a", "b", "c", "d"],
        "suggested_params": {"place_density": 0.62},
        "source": "llm",
    }
    payload = _decision_reason_structured_from_suggestion(
        suggestion,
        prefix="iter 2 -> 3",
    )

    assert payload["kind"] == "suggestion"
    assert payload["prefix"] == "iter 2 -> 3"
    assert payload["reasoning"] == ["a", "b", "c"]
    assert payload["suggested_params"]["place_density"] == 0.62
    assert payload["source"] == "llm"


def test_record_decision_trace_fallback_structured_reason():
    from eda_agent.agent.tools import _record_decision_trace

    db = MagicMock()
    with patch("eda_agent.agent.tools.get_db", return_value=_Ctx(db)):
        _record_decision_trace(
            session_id=1,
            source_run_id=10,
            target_run_id=11,
            llm_reason="fallback text",
        )

    execute_args, _ = db.execute.call_args
    params = execute_args[1]
    structured_raw = params["llm_reason_structured"]
    structured = json.loads(structured_raw)
    assert structured["kind"] == "text"
    assert structured["text"] == "fallback text"
