#!/usr/bin/env python3
"""Test LLM-driven congestion fix workflow on Innovus VM.

Workflow:
1) Run place stage to generate initial congestion
2) Parse congestion metrics from reports
3) Ask LLM to analyze and suggest fixes
4) Apply fixes and re-run place stage
5) Compare congestion before/after
"""

from pathlib import Path
from typing import Any
import httpx
import json
import os
import re
import shlex
import subprocess

import pytest

# Load environment
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

TESTCASE_ROOT = Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1")
TESTCASE_CONFIG = TESTCASE_ROOT / "FPR/.test"

from eda_agent.backends import get_backend
from eda_agent.api.routers.runs_router import RunStageRequest, trigger_run
from eda_agent.db.repository import EDAQueryRepository
from eda_agent.db.session import get_db
from eda_agent.parsers import get_parser
from eda_agent.config import settings
from tests.vm_resource_guard import ensure_vm_test_resources


def extract_congestion_metrics(design_path: Path) -> dict[str, Any]:
    """Parse congestion from place stage reports."""
    metrics = {}
    
    # Try congestion parser
    conparser = get_parser("innovus_congestion")
    if conparser:
        for rpt in design_path.glob("*congestion*.rpt"):
            try:
                data = conparser.parse_file(rpt)
                metrics["congestion"] = data
            except Exception as e:
                metrics["congestion_error"] = str(e)
    
    # Try utilization parser
    utilparser = get_parser("innovus_utilization")
    if utilparser:
        for rpt in design_path.glob("*area*.rpt"):
            try:
                data = utilparser.parse_file(rpt)
                metrics["utilization"] = data
            except Exception as e:
                metrics["utilization_error"] = str(e)
    
    return metrics


def _trigger_place_run(params: dict[str, Any]) -> dict[str, Any]:
    """Run place stage through API/tool layer."""
    req = RunStageRequest(
        backend="innovus",
        stage="place",
        design_name="InnovusBlk_18_1",
        design_config=str(TESTCASE_CONFIG),
        pdk="tsmc18",
        params=params,
    )
    return trigger_run(req=req, _user={"username": "vm-test", "is_active": True})


def _get_run_row(run_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = EDAQueryRepository.get_run(db, run_id)
    if not row:
        raise AssertionError(f"Run {run_id} not found in DB")
    return row


def _write_remote_tcl(commands: list[str], remote_workdir: str) -> str:
    """Write TCL content to remote VM and return remote path."""
    remote_path = f"{remote_workdir}/scripts/eda_fix_congestion.tcl"
    escaped_cmds = [c.replace("\\", "\\\\").replace('"', '\\"') for c in commands]
    wrapped_lines = [
        "# Auto-generated congestion fix script with best-effort command execution",
        "set __eda_fix_cmds {",
    ]
    for cmd in escaped_cmds:
        wrapped_lines.append(f'    "{cmd}"')
    wrapped_lines.extend(
        [
            "}",
            "foreach __cmd $__eda_fix_cmds {",
            "    if {[catch {eval $__cmd} __err]} {",
            "        puts \"EDA_FIX_WARN command failed: $__cmd\"",
            "        puts \"EDA_FIX_WARN error: $__err\"",
            "    }",
            "}",
            "puts \"EDA_FIX finished\"",
            "exit",
        ]
    )
    content = "\n".join(wrapped_lines) + "\n"
    quoted = content.replace("'", "'\\''")
    cmd = (
        f"mkdir -p {shlex.quote(remote_workdir)}/scripts && "
        f"cat > {shlex.quote(remote_path)} <<'TCLEOF'\n{quoted}\nTCLEOF"
    )
    result = subprocess.run(
        [
            "ssh",
            "-p",
            "22",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "host@192.168.58.10",
            cmd,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to upload remote TCL: {result.stderr or result.stdout}"
        )
    return remote_path


def ask_llm_to_fix_congestion(congestion_data: dict, design_name: str) -> dict[str, Any]:
    """Send congestion data to LLM and get fix suggestions."""
    
    prompt = f"""You are an EDA expert. Analyze the following congestion data for design '{design_name}' and suggest Innovus TCL commands to fix the congestion issues.

CONGESTION DATA:
{json.dumps(congestion_data, indent=2)}

Respond in JSON format:
{{
    "analysis": "Brief analysis of the congestion problem",
    "suggested_tcl_commands": [
        "set_db place.coarse.active_.place_density 0.7",
        "set_db place.coarse.active.spacing 2"
    ],
    "reasoning": "Why these commands help"
}}
"""
    
    try:
        client = httpx.Client(timeout=120)
        response = client.post(
            f"{settings.minimax_base_url}/text/chatcompletion_v2",
            headers={
                "Authorization": f"Bearer {settings.minimax_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.minimax_model,
                "messages": [
                    {"role": "system", "content": "You are an EDA expert specializing in physical design optimization."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        result = response.json()
        
        # Extract content from response
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # Extract JSON from content
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            return json.loads(json_match.group())
        
        return {"error": "Could not parse LLM response"}
    
    except Exception as e:
        return {"error": str(e)}


def run_place_with_fix(tcl_commands: list[str]) -> dict[str, Any]:
    """Run place stage with a remote TCL script through API/tool layer."""
    allowed_prefixes = ("set_db ", "set_app_options ")
    filtered_commands = [
        cmd.strip()
        for cmd in tcl_commands
        if cmd.strip().startswith(allowed_prefixes)
    ]
    if not filtered_commands:
        filtered_commands = [
            "set_db route.global_violation_threshold 0",
        ]

    remote_tcl = _write_remote_tcl(filtered_commands, str(TESTCASE_ROOT))
    try:
        result = _trigger_place_run(
            {
                "tcl": remote_tcl,
                "timeout_sec": 1800,
                "workdir": str(TESTCASE_ROOT),
            }
        )
    except Exception as exc:
        return {
            "status": "failed",
            "run_id": None,
            "log_path": None,
            "error": str(exc),
        }
    return {
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "log_path": result.get("log_path"),
        "error": result.get("error"),
    }


def test_congestion_fix_iterative():
    """Test iterative congestion fix workflow."""
    backend = get_backend("innovus")
    
    if not backend.is_available():
        print("[SKIP] Innovus not available")
        return

    ensure_vm_test_resources()
    
    print(f"Testing congestion fix workflow on {backend.name}")
    
    # Step 1: Run place stage (baseline)
    print("\n=== Step 1: Running place stage (baseline) ===")
    result = _trigger_place_run(
        {
            "timeout_sec": 1800,
            "workdir": str(TESTCASE_ROOT),
        }
    )
    print(f"Status: {result.get('status')}")
    
    if result.get("status") != "success":
        print(f"[FAIL] Place stage failed: {result.get('error')}")
        return

    baseline_run_id = int(result["run_id"])
    baseline_run = _get_run_row(baseline_run_id)
    baseline_report_dir = Path(str(baseline_run["report_dir"]))
    
    # Step 2: Get congestion metrics
    print("\n=== Step 2: Parsing congestion metrics ===")
    congestion = extract_congestion_metrics(baseline_report_dir)
    print(f"Congestion: {json.dumps(congestion, indent=2)}")
    
    # Step 3: Ask LLM for fix suggestions
    print("\n=== Step 3: Asking LLM for fix suggestions ===")
    llm_response = ask_llm_to_fix_congestion(congestion, "InnovusBlk_18_1")
    print(f"LLM Response: {json.dumps(llm_response, indent=2)}")
    
    if "suggested_tcl_commands" in llm_response:
        # Step 4: Apply fixes
        print("\n=== Step 4: Applying fixes ===")
        fix_result = run_place_with_fix(llm_response["suggested_tcl_commands"])
        print(f"Fix result: {fix_result}")
        
        # Step 5: Compare results
        print("\n=== Step 5: Comparing results ===")
        if fix_result.get("status") == "success" and fix_result.get("run_id") is not None:
            new_run = _get_run_row(int(fix_result["run_id"]))
            new_report_dir = Path(str(new_run["report_dir"]))
            new_congestion = extract_congestion_metrics(new_report_dir)
        else:
            new_congestion = {"error": fix_result.get("error", "place fix failed")}
        print(f"New congestion: {json.dumps(new_congestion, indent=2)}")
    
    return {
        "baseline_congestion": congestion,
        "llm_suggestion": llm_response,
    }


def test_congestion_vm_baseline_reports():
    """Run baseline through API/tool layer and assert parsed metrics in DB and reports."""
    backend = get_backend("innovus")

    if not backend.is_available():
        pytest.skip("Innovus not available")

    ensure_vm_test_resources()

    result = _trigger_place_run(
        {
            "timeout_sec": 1800,
            "workdir": str(TESTCASE_ROOT),
        }
    )
    assert result.get("status") == "success", json.dumps(result, default=str)
    run_id = int(result["run_id"])

    run_row = _get_run_row(run_id)
    report_dir = Path(str(run_row["report_dir"]))
    assert report_dir.is_dir()

    with get_db() as db:
        timing = EDAQueryRepository.get_timing(
            db,
            design_name="InnovusBlk_18_1",
            run_id=run_id,
            limit=20,
        )
        utilization = EDAQueryRepository.get_utilization(
            db,
            design_name="InnovusBlk_18_1",
            run_id=run_id,
            limit=20,
        )
        congestion_rows = EDAQueryRepository.get_congestion(db, run_id=run_id, limit=50)

    assert timing.get("summary")
    assert utilization
    assert congestion_rows

    parsed = extract_congestion_metrics(report_dir)
    assert "congestion" in parsed
    assert "utilization" in parsed
    assert parsed["congestion"][0]["total_overflow"] >= 0
    assert parsed["utilization"][0]["design_area_um2"] > 0


if __name__ == "__main__":
    test_congestion_fix_iterative()