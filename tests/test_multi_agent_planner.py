from __future__ import annotations

from eda_agent.agent.planner import Planner


def test_run_multi_agent_cycle_default_agents():
    planner = Planner(api_key="dummy", model="dummy", max_iterations=1)
    result = planner.run_multi_agent_cycle(
        objective="WNS >= -0.1 and overflow_h_pct <= 2.0",
        session_id=11,
        run_id=22,
    )

    assert result["objective"].startswith("WNS")
    assert result["contract_version"] == "v1"
    assert len(result["envelopes"]) == 4
    assert "status_summary" in result
    assert result["status_summary"]["total"] == 4
    assert "decision_view" in result
    assert result["gate"]["status"] in {"auto_execute", "needs_approval"}


def test_run_multi_agent_cycle_high_risk_needs_approval():
    planner = Planner(api_key="dummy", model="dummy", max_iterations=1)
    result = planner.run_multi_agent_cycle(
        objective="reduce congestion",
        constraints={"risk_level": "high"},
        inputs={"risk_level": "high"},
    )

    assert result["gate"]["blocked"] is True
    assert result["gate"]["status"] == "needs_approval"


def test_run_multi_agent_cycle_unknown_agent_yields_error_envelope():
    planner = Planner(api_key="dummy", model="dummy", max_iterations=1)
    result = planner.run_multi_agent_cycle(
        objective="debug signoff",
        agents=["pnr", "unknown_agent"],
    )

    env_by_agent = {e["agent"]: e for e in result["envelopes"]}
    assert env_by_agent["pnr"]["status"] == "ok"
    assert env_by_agent["unknown_agent"]["status"] == "error"
    assert result["status_summary"]["error"] >= 1
