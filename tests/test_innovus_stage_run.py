#!/usr/bin/env python3
"""Test running Innovus stages via LLM commands on VM."""

from pathlib import Path
from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec

# Test stages to run in order
TEST_STAGES = ["floorplan", "place", "route"]


def run_innovus_stage(stage: str, design: DesignSpec, backend) -> dict:
    """Run a single stage and return result."""
    params = {
        "timeout_sec": 1800,
    }
    
    result = backend.run_stage(stage, design, params)
    return {
        "stage": stage,
        "status": result.status.value,
        "run_id": result.run_id,
        "log_path": str(result.log_path),
        "error": result.error_message,
    }


def get_metrics_for_stage(stage: str, design: DesignSpec, backend) -> dict:
    """Parse and return metrics for a completed stage."""
    from eda_agent.parsers import get_parser
    
    metrics = {}
    report_type = f"innovus_{stage}"
    parser = get_parser(report_type)
    
    if parser and design.config_path:
        report_files = list(design.config_path.glob(f"*.rpt"))
        for rf in report_files:
            try:
                data = parser.parse(rf)
                metrics[rf.name] = data
            except Exception as e:
                metrics[rf.name] = {"error": str(e)}
    
    return metrics


def test_run_stages_via_llm():
    """Test running multiple stages via LLM."""
    backend = get_backend("innovus")
    
    # Check availability
    if not backend.is_available():
        print(f"[SKIP] Innovus not available (SSH not configured)")
        return
    
    print(f"Backend: {backend.name} v{backend.version}")
    
    design = DesignSpec(
        name="InnovusBlk_18_1",
        config_path=Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1"),
        pdk="unknown",
    )
    
    results = []
    for stage in TEST_STAGES:
        print(f"\n=== Running stage: {stage} ===")
        result = run_innovus_stage(stage, design, backend)
        results.append(result)
        
        print(f"Status: {result['status']}")
        if result['error']:
            print(f"Error: {result['error']}")
            break
        
        # Get metrics for this stage
        metrics = get_metrics_for_stage(stage, design, backend)
        print(f"Metrics: {metrics}")
    
    return results


if __name__ == "__main__":
    results = test_run_stages_via_llm()
    print(f"\n=== Summary ===")
    for r in results:
        print(f"{r['stage']}: {r['status']}")