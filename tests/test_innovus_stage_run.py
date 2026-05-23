#!/usr/bin/env python3
"""Test running Innovus stages via LLM commands on VM."""

from pathlib import Path

import pytest

from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec


TESTCASE_ROOT = Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1")
TESTCASE_CONFIG = TESTCASE_ROOT / "FPR/.test"
TEST_STAGES = ["floorplan", "place"]

def run_innovus_stage(stage: str, design: DesignSpec, backend):
    """Run a single stage and return the backend RunResult."""
    return backend.run_stage(
        stage,
        design,
        {
            "timeout_sec": 1800,
            # Ensure stage scripts restore from the real VM testcase tree.
            "workdir": str(TESTCASE_ROOT),
        },
    )


def get_metrics_for_stage(result, backend) -> dict:
    """Parse and return metrics for a completed stage using collected reports."""
    from eda_agent.parsers import get_parser

    metrics = {}
    for report in backend.collect_reports(result):
        parser = get_parser(report.report_type)
        if parser is None:
            continue
        try:
            metrics.setdefault(report.report_type, []).extend(parser.parse_file(report.path))
        except Exception as e:
            metrics.setdefault(report.report_type, []).append({"error": str(e)})

    return metrics


def test_run_innovus_vm_testcase_stages():
    """Run real testcase stages on VM via SSH and validate parsed reports."""
    backend = get_backend("innovus")

    # Check availability
    if not backend.is_available():
        pytest.skip("Innovus not available (SSH not configured)")

    design = DesignSpec(
        name="InnovusBlk_18_1",
        config_path=TESTCASE_CONFIG,
        pdk="unknown",
    )

    for stage in TEST_STAGES:
        result = run_innovus_stage(stage, design, backend)
        assert result.status.value == "success"
        assert result.log_path is not None and result.log_path.exists()
        assert result.report_dir is not None and result.report_dir.is_dir()

        reports = backend.collect_reports(result)
        assert reports

        report_types = {report.report_type for report in reports}

        metrics = get_metrics_for_stage(result, backend)
        assert metrics

        if stage == "floorplan":
            assert "innovus_utilization" in report_types
            assert any(item.get("kind") == "summary" for item in metrics.get("innovus_utilization", []))
        elif stage == "place":
            assert "innovus_timing" in report_types
            assert "innovus_congestion" in report_types
            assert "innovus_utilization" in report_types
            assert any(item.get("kind") == "summary" for item in metrics.get("innovus_timing", []))
            assert any(item.get("kind") == "summary" for item in metrics.get("innovus_congestion", []))


if __name__ == "__main__":
    test_run_innovus_vm_testcase_stages()
    print("VM testcase stage regression passed")