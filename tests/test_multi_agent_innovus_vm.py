#!/usr/bin/env python3
"""VM smoke test for multi-agent orchestration -> Innovus experiment execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eda_agent.agent.tools import execute_tool
from eda_agent.backends import get_backend
from tests.vm_resource_guard import ensure_vm_test_resources


TESTCASE_ROOT = Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1")


def test_multi_agent_cycle_vm_smoke_executes_innovus_place():
    """Smoke: run multi-agent cycle and execute one Innovus place experiment.

    This test is intentionally lightweight and skips when Innovus VM is not
    available in the current environment.
    """
    backend = get_backend("innovus")
    if not backend.is_available():
        pytest.skip("Innovus not available (SSH not configured)")

    ensure_vm_test_resources()

    payload = {
        "objective": "Reduce congestion while keeping timing stable",
        "constraints": {"risk_level": "low"},
        "execute_experiment": True,
        "experiment_request": {
            "backend": "innovus",
            "stage": "place",
            "design_name": "InnovusBlk_18_1",
            "innovus_workdir": str(TESTCASE_ROOT),
            "tech_profile": "tsmc18",
            "params": {
                "timeout_sec": 1800,
                "workdir": str(TESTCASE_ROOT),
            },
        },
    }

    result = json.loads(execute_tool("run_multi_agent_cycle", payload))
    assert "multi_agent" in result, json.dumps(result, ensure_ascii=False)
    assert "experiment_execution" in result, json.dumps(result, ensure_ascii=False)

    execution = result["experiment_execution"]
    assert execution.get("status") == "success", json.dumps(result, ensure_ascii=False)

    run_result = execution.get("result") or {}
    assert isinstance(run_result.get("run_id"), int)
    assert run_result.get("stage") == "place"
    assert run_result.get("backend") == "innovus"
