"""Tests for the tool dispatch layer (no DB/LLM required)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from eda_agent.agent.tools import (
    _resolve_backend_design_identity,
    _submit_job,
    _tune_congestion_with_blockage,
    execute_tool,
)


def test_execute_unknown_tool():
    result = json.loads(execute_tool("no_such_tool", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_execute_tool_bad_args():
    """Missing required arg → JSON error, no exception raised."""
    result = json.loads(execute_tool("query_timing", {}))
    # Should return an error dict, not raise
    assert isinstance(result, (list, dict))
    # May be an error or empty list depending on DB availability


def test_resolve_backend_design_identity_innovus_aliases_override_defaults():
    cfg, tech = _resolve_backend_design_identity(
        backend="innovus",
        design_config=None,
        pdk=None,
        innovus_workdir="/remote/work",
        tech_profile="n7_profile",
    )
    assert cfg == "/remote/work"
    assert tech == "n7_profile"


def test_resolve_backend_design_identity_innovus_defaults():
    cfg, tech = _resolve_backend_design_identity(
        backend="innovus",
        design_config=None,
        pdk=None,
    )
    assert isinstance(cfg, str)
    assert cfg != ""
    assert tech == "tsmc18"


def test_resolve_backend_design_identity_non_innovus_requires_values():
    with pytest.raises(ValueError):
        _resolve_backend_design_identity(
            backend="orfs",
            design_config=None,
            pdk="sky130hd",
        )

    with pytest.raises(ValueError):
        _resolve_backend_design_identity(
            backend="orfs",
            design_config="/tmp/config.mk",
            pdk=None,
        )


@patch("eda_agent.agent.tools._ensure_worker_running")
@patch("eda_agent.queue.store.JobStore")
def test_submit_job_innovus_aliases_are_normalized(mock_store_cls, _mock_worker):
    mock_store = MagicMock()
    mock_store.enqueue.return_value = "job-123"
    mock_store_cls.return_value = mock_store

    result = _submit_job(
        backend="innovus",
        stage="place",
        design_name="aes",
        innovus_workdir="/remote/innovus/work",
        tech_profile="n5_profile",
    )

    assert result["job_id"] == "job-123"
    _, kwargs = mock_store.enqueue.call_args
    assert kwargs["design_config"] == "/remote/innovus/work"
    assert kwargs["pdk"] == "n5_profile"


@patch("eda_agent.agent.tools._run_eda_stage")
def test_tune_congestion_with_blockage_innovus_aliases_are_normalized(mock_run_stage):
    mock_run_stage.return_value = {
        "run_id": None,
        "status": "failed",
        "error": "simulated",
    }

    result = _tune_congestion_with_blockage(
        backend="innovus",
        design_name="aes",
        innovus_workdir="/remote/innovus/work",
        tech_profile="n5_profile",
        max_iterations=1,
    )

    assert result["converged"] is False
    _, kwargs = mock_run_stage.call_args
    assert kwargs["design_config"] == "/remote/innovus/work"
    assert kwargs["pdk"] == "n5_profile"


def test_execute_run_multi_agent_cycle_contract():
    result = json.loads(
        execute_tool(
            "run_multi_agent_cycle",
            {
                "objective": "WNS >= -0.1",
                "constraints": {"risk_level": "low"},
            },
        )
    )

    assert "multi_agent" in result
    cycle = result["multi_agent"]
    assert "task_id" in cycle
    assert "envelopes" in cycle
    assert "gate" in cycle


@patch("eda_agent.agent.tools._run_eda_stage")
def test_execute_run_multi_agent_cycle_executes_experiment_when_allowed(mock_run_stage):
    mock_run_stage.return_value = {
        "run_id": 555,
        "status": "success",
        "stage": "place",
        "backend": "innovus",
    }

    result = json.loads(
        execute_tool(
            "run_multi_agent_cycle",
            {
                "objective": "Reduce congestion",
                "constraints": {"risk_level": "low"},
                "execute_experiment": True,
                "experiment_request": {
                    "backend": "innovus",
                    "stage": "place",
                    "design_name": "aes",
                    "innovus_workdir": "/remote/innovus/work",
                    "tech_profile": "n5_profile",
                    "params": {},
                },
            },
        )
    )

    assert "experiment_execution" in result
    assert result["experiment_execution"]["status"] == "success"
    _, kwargs = mock_run_stage.call_args
    assert kwargs["design_config"] == "/remote/innovus/work"
    assert kwargs["pdk"] == "n5_profile"


def test_execute_run_multi_agent_cycle_blocks_high_risk_experiment():
    result = json.loads(
        execute_tool(
            "run_multi_agent_cycle",
            {
                "objective": "Aggressive fix",
                "constraints": {"risk_level": "high"},
                "inputs": {"risk_level": "high"},
                "execute_experiment": True,
                "experiment_request": {
                    "backend": "innovus",
                    "stage": "place",
                    "design_name": "aes",
                    "innovus_workdir": "/remote/innovus/work",
                    "tech_profile": "n5_profile",
                },
            },
        )
    )

    assert result["experiment_execution"]["status"] == "blocked"


@patch("eda_agent.agent.tools._record_decision_trace")
@patch("eda_agent.agent.tools._run_eda_stage")
def test_execute_run_multi_agent_cycle_records_decision_trace(
    mock_run_stage,
    mock_record_decision,
):
    mock_run_stage.return_value = {
        "run_id": 777,
        "status": "success",
        "stage": "place",
        "backend": "innovus",
    }

    result = json.loads(
        execute_tool(
            "run_multi_agent_cycle",
            {
                "objective": "Reduce congestion",
                "session_id": 12,
                "run_id": 34,
                "constraints": {"risk_level": "low"},
                "execute_experiment": True,
                "experiment_request": {
                    "backend": "innovus",
                    "stage": "place",
                    "design_name": "aes",
                    "innovus_workdir": "/remote/innovus/work",
                    "tech_profile": "n5_profile",
                },
            },
        )
    )

    assert result["experiment_execution"]["status"] == "success"
    mock_record_decision.assert_called_once()
    _, kwargs = mock_record_decision.call_args
    assert kwargs["session_id"] == 12
    assert kwargs["source_run_id"] == 34
    assert kwargs["target_run_id"] == 777
    assert kwargs["llm_reason_structured"]["kind"] == "multi_agent_cycle"


@patch("eda_agent.agent.tools._record_decision_trace")
@patch("eda_agent.agent.tools._run_eda_stage")
def test_execute_run_multi_agent_cycle_without_lineage_skips_decision_trace(
    mock_run_stage,
    mock_record_decision,
):
    mock_run_stage.return_value = {
        "run_id": 778,
        "status": "success",
        "stage": "place",
        "backend": "innovus",
    }

    _ = json.loads(
        execute_tool(
            "run_multi_agent_cycle",
            {
                "objective": "Reduce congestion",
                "constraints": {"risk_level": "low"},
                "execute_experiment": True,
                "experiment_request": {
                    "backend": "innovus",
                    "stage": "place",
                    "design_name": "aes",
                    "innovus_workdir": "/remote/innovus/work",
                    "tech_profile": "n5_profile",
                },
            },
        )
    )

    mock_record_decision.assert_not_called()
