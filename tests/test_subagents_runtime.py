from __future__ import annotations

from unittest.mock import patch

from eda_agent.agent.subagents.base import AgentEnvelope
from eda_agent.agent.subagents.pnr_agent import PnRAgent
from eda_agent.agent.subagents.signoff_agent import SignoffAgent
from eda_agent.agent.subagents.sta_agent import STAAgent


def _task(agent: str) -> AgentEnvelope:
    return AgentEnvelope(
        task_id="t-1",
        agent=agent,
        run_id=101,
        objective="WNS >= -0.1 and overflow_h_pct <= 2.0",
        inputs={"design_name": "aes", "stage": "place"},
    )


@patch("eda_agent.agent.inference.engine.infer")
def test_pnr_agent_runs_inference_and_builds_experiments(mock_infer):
    mock_infer.return_value = {
        "hypotheses": [
            {
                "cause_id": "routing_detour",
                "display_name": "Routing Detour",
                "experiments": [
                    {"action": "increase_cong_effort", "risk": "low", "param_hint": {"place_cong_effort": "high"}}
                ],
            }
        ]
    }

    env = PnRAgent().run(_task("pnr"))

    assert env.status == "ok"
    assert env.outputs["hypotheses"]
    assert env.outputs["candidate_experiments"]
    assert env.outputs["candidate_experiments"][0]["cause_id"] == "routing_detour"


@patch("eda_agent.agent.tools._query_timing")
def test_sta_agent_runs_timing_query_and_generates_warnings(mock_query_timing):
    mock_query_timing.return_value = {
        "summary": [
            {
                "wns_ns": -0.2,
                "setup_violations": 2,
                "hold_violations": 1,
            }
        ],
        "paths": [
            {"startpoint": "u1/a", "endpoint": "u2/z", "slack_ns": -0.2}
        ],
    }

    env = STAAgent().run(_task("sta"))

    assert env.status == "ok"
    assert env.outputs["critical_paths_summary"]
    warnings = env.outputs["constraint_warnings"]
    assert "negative_wns" in warnings
    assert "setup_violations_detected" in warnings
    assert "hold_violations_detected" in warnings


@patch("eda_agent.agent.tools._query_power")
@patch("eda_agent.agent.tools._query_utilization")
def test_signoff_agent_runs_power_util_queries_and_sets_ready(
    mock_query_util,
    mock_query_power,
):
    mock_query_util.return_value = [{"utilization_pct": 72.0}]
    mock_query_power.return_value = [{"total_power_w": 1.8}]

    env = SignoffAgent().run(_task("signoff"))

    assert env.status == "ok"
    assert env.outputs["power_summary"]
    assert env.outputs["utilization_summary"]
    assert env.outputs["signoff_ready"] is True
