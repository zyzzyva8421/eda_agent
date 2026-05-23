#!/usr/bin/env python3
"""Test running Innovus stages via LLM commands on VM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eda_agent.backends import get_backend
from eda_agent.api.routers.runs_router import RunStageRequest, trigger_run
from eda_agent.db.repository import EDAQueryRepository
from eda_agent.db.session import get_db
from tests.vm_resource_guard import ensure_vm_test_resources


TESTCASE_ROOT = Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1")
TESTCASE_CONFIG = TESTCASE_ROOT / "FPR/.test"
TEST_STAGES = ["floorplan", "place"]

def run_innovus_stage(stage: str) -> dict:
    """Run one stage through API/tool layer and return the response payload."""
    req = RunStageRequest(
        backend="innovus",
        stage=stage,
        design_name="InnovusBlk_18_1",
        design_config=str(TESTCASE_CONFIG),
        pdk="tsmc18",
        params={
            "timeout_sec": 1800,
            "workdir": str(TESTCASE_ROOT),
        },
    )
    return trigger_run(req=req, _user={"username": "vm-test", "is_active": True})


def get_metrics_for_stage(run_id: int, stage: str) -> dict[str, object]:
    """Read parsed metrics from DB for the given run."""
    with get_db() as db:
        utilization = EDAQueryRepository.get_utilization(
            db,
            design_name="InnovusBlk_18_1",
            run_id=run_id,
            limit=20,
        )
        timing = EDAQueryRepository.get_timing(
            db,
            design_name="InnovusBlk_18_1",
            run_id=run_id,
            limit=20,
        )
        congestion = EDAQueryRepository.get_congestion(
            db,
            run_id=run_id,
            limit=50,
        )
        run_row = EDAQueryRepository.get_run(db, run_id)

    return {
        "stage": stage,
        "run": run_row,
        "utilization": utilization,
        "timing": timing,
        "congestion": congestion,
    }


def test_run_innovus_vm_testcase_stages():
    """Run VM testcase stages through API/tool layer and validate DB-ingested metrics."""
    backend = get_backend("innovus")

    # Check availability
    if not backend.is_available():
        pytest.skip("Innovus not available (SSH not configured)")

    ensure_vm_test_resources()

    for stage in TEST_STAGES:
        result = run_innovus_stage(stage)
        assert result["status"] == "success", json.dumps(result, default=str)
        run_id = int(result["run_id"])
        metrics = get_metrics_for_stage(run_id, stage)

        run_row = metrics["run"]
        assert isinstance(run_row, dict)
        assert Path(str(run_row["log_path"])).exists()
        assert Path(str(run_row["report_dir"])).is_dir()

        if stage == "floorplan":
            utilization = metrics["utilization"]
            assert isinstance(utilization, list) and utilization
            assert utilization[0].get("design_area_um2", 0) > 0
        elif stage == "place":
            utilization = metrics["utilization"]
            timing = metrics["timing"]
            congestion = metrics["congestion"]

            assert isinstance(utilization, list) and utilization
            assert isinstance(timing, dict) and timing.get("summary")
            assert isinstance(congestion, list) and congestion


if __name__ == "__main__":
    test_run_innovus_vm_testcase_stages()
    print("VM testcase stage regression passed")