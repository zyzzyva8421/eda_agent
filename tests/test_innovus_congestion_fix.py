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

# Load environment
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec
from eda_agent.parsers import get_parser
from eda_agent.config import settings


def extract_congestion_metrics(design_path: Path) -> dict[str, Any]:
    """Parse congestion from place stage reports."""
    metrics = {}
    
    # Try congestion parser
    conparser = get_parser("innovus_congestion")
    if conparser:
        for rpt in design_path.glob("*congestion*.rpt"):
            try:
                data = conparser.parse(rpt)
                metrics["congestion"] = data
            except Exception as e:
                metrics["congestion_error"] = str(e)
    
    # Try utilization parser
    utilparser = get_parser("innovus_utilization")
    if utilparser:
        for rpt in design_path.glob("*area*.rpt"):
            try:
                data = utilparser.parse(rpt)
                metrics["utilization"] = data
            except Exception as e:
                metrics["utilization_error"] = str(e)
    
    return metrics


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


def run_place_with_fix(design: DesignSpec, backend, tcl_commands: list[str]) -> dict:
    """Run place stage with custom TCL commands."""
    
    # Combine commands into TCL script
    tcl_content = "\n".join(tcl_commands)
    tcl_file = Path("/tmp/eda_fix_congestion.tcl")
    tcl_file.write_text(tcl_content)
    
    params = {
        "tcl": str(tcl_file),
        "timeout_sec": 1800,
    }
    
    result = backend.run_stage("place", design, params)
    return {
        "status": result.status.value,
        "log_path": str(result.log_path),
        "error": result.error_message,
    }


def test_congestion_fix_iterative():
    """Test iterative congestion fix workflow."""
    
    backend = get_backend("innovus")
    
    if not backend.is_available():
        print("[SKIP] Innovus not available")
        return
    
    print(f"Testing congestion fix workflow on {backend.name}")
    
    design = DesignSpec(
        name="InnovusBlk_18_1",
        config_path=Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR/.test"),
        pdk="unknown",
    )
    
    # Step 1: Run place stage (baseline)
    print("\n=== Step 1: Running place stage (baseline) ===")
    result = backend.run_stage("place", design, {"timeout_sec": 1800})
    print(f"Status: {result.status.value}")
    
    if result.status.value != "success":
        print(f"[FAIL] Place stage failed: {result.error_message}")
        return
    
    # Step 2: Get congestion metrics
    print("\n=== Step 2: Parsing congestion metrics ===")
    congestion = extract_congestion_metrics(design.config_path)
    print(f"Congestion: {json.dumps(congestion, indent=2)}")
    
    # Step 3: Ask LLM for fix suggestions
    print("\n=== Step 3: Asking LLM for fix suggestions ===")
    llm_response = ask_llm_to_fix_congestion(congestion, design.name)
    print(f"LLM Response: {json.dumps(llm_response, indent=2)}")
    
    if "suggested_tcl_commands" in llm_response:
        # Step 4: Apply fixes
        print("\n=== Step 4: Applying fixes ===")
        fix_result = run_place_with_fix(design, backend, llm_response["suggested_tcl_commands"])
        print(f"Fix result: {fix_result}")
        
        # Step 5: Compare results
        print("\n=== Step 5: Comparing results ===")
        new_congestion = extract_congestion_metrics(design.config_path)
        print(f"New congestion: {json.dumps(new_congestion, indent=2)}")
    
    return {
        "baseline_congestion": congestion,
        "llm_suggestion": llm_response,
    }


if __name__ == "__main__":
    test_congestion_fix_iterative()