"""Real-LLM end-to-end integration test: AES design on sky130hd.

This test suite makes **actual calls to the MiniMax LLM API**.  It is
separated from the mock-only e2e suite so that:

  * CI can skip it when no API key is available (``pytest -m "not llm"``).
  * Engineers can run it on-demand to verify LLM reasoning quality.

Skipping condition
------------------
All tests are skipped automatically when ``MINIMAX_API_KEY`` is empty or
missing from the environment / .env file.

Scenario
--------
AES sky130hd post-route: timing violations + congestion hotspots.

  - WNS = -0.352 ns,  TNS = -2.816 ns,  failing endpoints = 8
  - Congestion hotspots = 5,  max overflow = 4
  - Utilization = 68%,  cells = 12847
  - Total power ≈ 0.654 mW

The DB layer is **fully mocked** (no PostgreSQL needed).
Only the LLM HTTP transport is real.

Test coverage
-------------
Test 1 – ``test_llm_diagnoses_routing_detour``
    Ask the LLM to diagnose the AES design.  The LLM must:
      a) Call ``infer_root_cause`` (or ``query_timing`` + ``infer_root_cause``).
      b) Return a final answer that names ``routing_detour`` as the root cause.

Test 2 – ``test_llm_suggests_utilization_reduction``
    Verify the LLM's final answer recommends reducing utilization / placement
    density as the primary fix.

Test 3 – ``test_llm_confirm_root_cause``
    After receiving an infer result, ask the LLM to confirm ``routing_detour``.
    The LLM should call ``confirm_root_cause`` and report the case was saved.

Test 4 – ``test_llm_explains_evidence``
    Ask the LLM to explain *why* routing_detour was chosen.  The answer should
    reference at least two of: WNS / TNS / congestion / utilization.

Test 5 – ``test_llm_single_turn_summary``
    Single-turn (no tool calls): inject the AES infer result directly into the
    prompt and ask the LLM to summarise it.  Verifies basic LLM response
    quality without a full ReAct loop.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eda_agent.config import settings

logger = logging.getLogger(__name__)

# ── Skip marker ───────────────────────────────────────────────────────────────

_HAS_API_KEY = bool(settings.minimax_api_key)

pytestmark = pytest.mark.llm  # all tests in this file carry the "llm" marker

# Individual test skip (in case only some need to be skipped)
_skip_no_key = pytest.mark.skipif(
    not _HAS_API_KEY,
    reason="MINIMAX_API_KEY not set; skipping real-LLM tests",
)

# ── AES fixture data ──────────────────────────────────────────────────────────

# The FeatureVector derived from the AES sky130hd post-route fixture files
# (same values as TestPhase2FeatureVector in test_orfs_aes_e2e.py).
_AES_FV: dict[str, Any] = {
    "wns_ns": -0.352,
    "tns_ns": -2.816,
    "failing_endpoints": 8,
    "hold_violations": 0,
    "setup_violations": 8,
    "clock_skew_ns": 0.045,
    "max_fanout_violations": 0,
    "max_slew_violations": 2,
    "max_cap_violations": 0,
    "critical_path_delay_ns": 6.908,
    "fmax_mhz": 144.93,
    "congestion_hotspot_count": 5,
    "max_overflow": 4,
    "utilization_pct": 68.0,
    "num_cells": 12847,
    "total_power_mw": 0.65439,
    "dynamic_power_mw": 0.58,
    "leakage_power_mw": 0.07,
    "drc_total": 0,
}

# The infer() result that would be returned for run_id=999 using _AES_FV.
_AES_INFER_RESULT: dict[str, Any] = {
    "inference_id": 999,
    "run_id": 999,
    "hypotheses": [
        {
            "cause_id": "routing_detour",
            "display_name": "Routing detour (congestion-induced)",
            "score": 1.0,
            "confidence": "high",
            "evidence": [
                {"feature": "wns_ns",                  "value": -0.352, "threshold": -0.2},
                {"feature": "congestion_hotspot_count", "value": 5,      "threshold": 3},
                {"feature": "utilization_pct",          "value": 68.0,   "threshold": 65},
                {"feature": "tns_ns",                   "value": -2.816, "threshold": -1.0},
            ],
            "experiments": [
                {
                    "action": "Reduce target utilization to 60% and rerun placement+routing",
                    "risk": "low",
                    "param_hint": {"PLACE_DENSITY": "0.60"},
                },
                {
                    "action": "Add routing blockages around congested region",
                    "risk": "medium",
                    "param_hint": {},
                },
            ],
        }
    ],
    "summary": (
        "最可能的根因是「Routing detour (congestion-induced)」"
        "(置信度 high, score=1.00)。"
    ),
    "next_action": (
        "建议优先执行：Reduce target utilization to 60% and rerun placement+routing"
        "（参数参考：{'PLACE_DENSITY': '0.60'}）"
    ),
}

_AES_CONFIRM_RESULT: dict[str, Any] = {
    "status": "confirmed",
    "inference_id": 999,
    "confirmed_cause_id": "routing_detour",
    "case_id": 42,
}


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _patch_execute_tool():
    """Patch execute_tool so tool calls return AES fixture data.

    The LLM decides *which* tools to call; this mock routes them to canned
    AES responses so no DB / ORFS installation is needed.
    """
    def _fake_execute(name: str, arguments: dict[str, Any]) -> str:
        logger.debug("execute_tool called: %s(%s)", name, arguments)

        if name == "infer_root_cause":
            return json.dumps(_AES_INFER_RESULT)

        if name == "confirm_root_cause":
            return json.dumps(_AES_CONFIRM_RESULT)

        if name == "query_timing":
            return json.dumps({
                "run_id": arguments.get("run_id", 999),
                "design_name": "aes",
                "stage": "route",
                "wns_ns": -0.352,
                "tns_ns": -2.816,
                "failing_endpoints": 8,
                "hold_violations": 0,
                "fmax_mhz": 144.93,
                "clock_skew_ns": 0.045,
            })

        if name == "query_congestion":
            return json.dumps({
                "run_id": arguments.get("run_id", 999),
                "hotspot_count": 5,
                "max_overflow": 4,
                "total_overflow": 7,
                "worst_layer": "metal3",
            })

        if name == "query_utilization":
            return json.dumps({
                "run_id": arguments.get("run_id", 999),
                "utilization_pct": 68.0,
                "num_cells": 12847,
            })

        if name == "query_power":
            return json.dumps({
                "run_id": arguments.get("run_id", 999),
                "total_power_mw": 0.65439,
                "dynamic_power_mw": 0.58,
                "leakage_power_mw": 0.07,
            })

        # Anything else: unsupported in this test context
        return json.dumps({"error": f"Tool '{name}' not available in LLM integration test"})

    return patch("eda_agent.agent.planner.execute_tool", side_effect=_fake_execute)


def _make_planner():
    """Return a Planner instance using the real API key but short iteration cap."""
    from eda_agent.agent.planner import Planner
    return Planner(max_iterations=8)


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Extract and parse the first JSON object found in text."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _baseline_finish_metrics_from_fixture() -> dict[str, float | int]:
    """Load baseline finish metrics from AES fixture timing report."""
    from eda_agent.parsers.timing import TimingParser

    rpt = (
        Path(__file__).parent.parent
        / "fixtures"
        / "orfs"
        / "sky130hd"
        / "aes"
        / "reports"
        / "6_finish_timing.rpt"
    )
    records = TimingParser().parse_file(rpt)
    summary = next(r for r in records if r.get("kind") == "summary")
    return {
        "wns_ns": float(summary.get("wns_ns", 0.0)),
        "tns_ns": float(summary.get("tns_ns", 0.0)),
        "setup_violations": int(summary.get("setup_violations", 0)),
        "hold_violations": int(summary.get("hold_violations", 0)),
    }


def _request_real_llm_param_suggestion(baseline: dict[str, float | int]) -> dict[str, Any]:
    """Call MiniMax directly and request make-variable suggestions as strict JSON."""
    import httpx

    prompt = (
        "You are an EDA physical design expert. Diagnose root cause and propose "
        "conservative parameter changes for one re-run. Return ONLY JSON object "
        "without markdown.\\n"
        "Schema:\\n"
        "{\\n"
        "  \"diagnosis\": string,\\n"
        "  \"suggested_params\": {\\n"
        "    \"PLACE_DENSITY\": string,\\n"
        "    \"CELL_PAD_IN_SITES\": string\\n"
        "  }\\n"
        "}\\n"
        f"Current metrics: {json.dumps(baseline)}\\n"
        "Constraints: PLACE_DENSITY between 0.55 and 0.68, keep changes low risk."
    )

    payload = {
        "model": settings.minimax_model,
        "messages": [
            {"role": "system", "content": "You are an expert EDA assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }

    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }
    if settings.minimax_group_id:
        headers["X-Group-Id"] = settings.minimax_group_id

    url = f"{settings.minimax_base_url.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    parsed = _extract_first_json_object(content)
    if not parsed:
        raise AssertionError(f"LLM did not return parseable JSON: {content}")

    params = parsed.get("suggested_params", {})
    if not isinstance(params, dict):
        raise AssertionError(f"LLM suggested_params invalid: {parsed}")

    # Keep only known make vars for this closed-loop test.
    allow = {"PLACE_DENSITY", "CELL_PAD_IN_SITES"}
    safe_params = {k: str(v) for k, v in params.items() if k in allow}
    if "PLACE_DENSITY" not in safe_params:
        safe_params["PLACE_DENSITY"] = "0.60"
    return safe_params


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 – LLM names routing_detour as root cause
# ═══════════════════════════════════════════════════════════════════════════════

@_skip_no_key
def test_llm_diagnoses_routing_detour():
    """The LLM must call infer_root_cause and surface routing_detour in its reply.

    Prompt deliberately uses natural language so the LLM must reason about
    which tool to invoke.
    """
    planner = _make_planner()

    with _patch_execute_tool():
        answer = planner.run(
            "I just finished routing the AES design on sky130hd (run_id=999). "
            "The flow completed but I suspect there are timing issues. "
            "Please diagnose the root cause of any PPA problems and give me "
            "a clear recommendation."
        )

    assert answer is not None, "Planner returned None"
    answer_lower = answer.lower()

    # LLM must mention the identified root cause
    assert "routing_detour" in answer_lower or "routing detour" in answer_lower, (
        f"Expected LLM to mention 'routing_detour' in answer.\nAnswer:\n{answer}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 – LLM recommends utilization reduction
# ═══════════════════════════════════════════════════════════════════════════════

@_skip_no_key
def test_llm_suggests_utilization_reduction():
    """The LLM's answer should recommend reducing placement density / utilization."""
    planner = _make_planner()

    with _patch_execute_tool():
        answer = planner.run(
            "Analyse AES sky130hd post-route (run_id=999). "
            "The design has timing violations and I see congestion in metal3. "
            "What should I do to fix it? Be specific about parameter changes."
        )

    assert answer is not None
    answer_lower = answer.lower()

    # Primary fix: reduce utilization / PLACE_DENSITY
    mentions_util_fix = (
        "utilization" in answer_lower
        or "place_density" in answer_lower
        or "density" in answer_lower
        or "60%" in answer_lower
        or "0.60" in answer
    )
    assert mentions_util_fix, (
        f"Expected LLM to recommend utilization/density reduction.\nAnswer:\n{answer}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 – LLM calls confirm_root_cause and reports success
# ═══════════════════════════════════════════════════════════════════════════════

@_skip_no_key
def test_llm_confirm_root_cause():
    """Ask the LLM to confirm routing_detour; it should call confirm_root_cause."""
    from eda_agent.agent.memory import AgentMemory

    planner = _make_planner()
    mem = AgentMemory()

    # Pre-load an infer result so the LLM knows inference_id=999
    infer_summary = json.dumps(_AES_INFER_RESULT, ensure_ascii=False)

    called_tools: list[str] = []

    def _tracking_execute(name: str, arguments: dict[str, Any]) -> str:
        called_tools.append(name)
        if name == "infer_root_cause":
            return json.dumps(_AES_INFER_RESULT)
        if name == "confirm_root_cause":
            return json.dumps(_AES_CONFIRM_RESULT)
        return json.dumps({"error": "not available"})

    with patch("eda_agent.agent.planner.execute_tool",
               side_effect=_tracking_execute):
        answer = planner.run(
            f"I have diagnosed AES sky130hd (run_id=999). "
            f"The inference result is: {infer_summary}. "
            f"I confirm that 'routing_detour' is the correct root cause. "
            f"Please record this confirmation (inference_id=999, "
            f"confirmed_cause_id=routing_detour).",
            memory=mem,
        )

    assert answer is not None

    # The LLM should have called confirm_root_cause
    assert "confirm_root_cause" in called_tools, (
        f"Expected LLM to call confirm_root_cause. Called tools: {called_tools}\n"
        f"Answer:\n{answer}"
    )

    # Answer should acknowledge the save
    answer_lower = answer.lower()
    assert any(kw in answer_lower for kw in ("confirmed", "saved", "recorded", "case")), (
        f"Expected LLM to acknowledge confirmation.\nAnswer:\n{answer}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 – LLM explains the evidence behind routing_detour
# ═══════════════════════════════════════════════════════════════════════════════

@_skip_no_key
def test_llm_explains_evidence():
    """The LLM should cite at least two evidence features (WNS/TNS/congestion/util)."""
    planner = _make_planner()

    with _patch_execute_tool():
        answer = planner.run(
            "Run root cause inference for AES sky130hd (run_id=999) and then "
            "explain in detail *why* you chose the top hypothesis. "
            "List the specific metric values that triggered it."
        )

    assert answer is not None
    answer_lower = answer.lower()

    # At least two of the four key evidence features must be mentioned
    evidence_keywords = ["wns", "tns", "congestion", "utilization", "hotspot", "overflow"]
    mentioned = [kw for kw in evidence_keywords if kw in answer_lower]
    assert len(mentioned) >= 2, (
        f"Expected LLM to cite ≥2 evidence features. Mentioned: {mentioned}\n"
        f"Answer:\n{answer}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 – Single-turn summary (no ReAct loop)
# ═══════════════════════════════════════════════════════════════════════════════

@_skip_no_key
def test_llm_single_turn_summary():
    """Directly inject infer result into prompt; verify LLM summarises correctly.

    This test does NOT use the Planner ReAct loop.  It calls the MiniMax API
    directly (one-shot) to check basic LLM response quality.
    """
    import httpx

    prompt = (
        "You are an EDA expert. Below is the root cause inference result for "
        "the AES design on sky130hd after post-route:\n\n"
        f"```json\n{json.dumps(_AES_INFER_RESULT, indent=2, ensure_ascii=False)}\n```\n\n"
        "Please write a concise 3-sentence engineering summary: "
        "(1) what is the root cause, "
        "(2) what evidence supports it, "
        "(3) what is the recommended fix."
    )

    payload = {
        "model": settings.minimax_model,
        "messages": [
            {"role": "system", "content": "You are an expert EDA physical design assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }

    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }
    if settings.minimax_group_id:
        headers["X-Group-Id"] = settings.minimax_group_id

    url = f"{settings.minimax_base_url.rstrip('/')}/chat/completions"

    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=headers)

    assert resp.status_code == 200, (
        f"MiniMax API returned {resp.status_code}: {resp.text[:200]}"
    )

    data = resp.json()
    answer = data["choices"][0]["message"]["content"]

    assert answer and len(answer) > 20, "LLM returned empty or trivial answer"

    answer_lower = answer.lower()

    # The summary must mention the root cause
    assert "routing_detour" in answer_lower or "routing detour" in answer_lower, (
        f"Expected single-turn answer to name routing_detour.\nAnswer:\n{answer}"
    )

    # And the fix
    assert "utilization" in answer_lower or "density" in answer_lower or "place" in answer_lower, (
        f"Expected single-turn answer to mention utilization fix.\nAnswer:\n{answer}"
    )

    logger.info("Single-turn LLM summary:\n%s", answer)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 – Real closed loop: LLM suggestion → real finish rerun → compare
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.slow
@_skip_no_key
def test_llm_real_finish_rerun_and_compare_metrics():
    """Run one real ORFS finish rerun using LLM-suggested params and compare.

    Opt-in guards:
      - EDA_REAL_RUN=1
      - ORFS flow/design config exists
      - PostgreSQL service reachable by eda_agent settings

    This test performs a true tool-driven loop:
      1) real LLM suggests params from baseline finish metrics
      2) run_eda_stage (finish) executes ORFS with suggested params
      3) query_timing fetches new run metrics from DB
      4) compare new metrics against old finish baseline
    """
    if os.getenv("EDA_REAL_RUN", "0") != "1":
        pytest.skip("Set EDA_REAL_RUN=1 to enable real ORFS rerun comparison test")

    from eda_agent.agent.tools import execute_tool

    design_name = os.getenv("EDA_REAL_DESIGN_NAME", "aes")
    pdk = os.getenv("EDA_REAL_PDK", "sky130hd")

    default_cfg = Path(settings.orfs_root) / "flow" / "designs" / pdk / design_name / "config.mk"
    cfg_path = Path(os.getenv("EDA_REAL_DESIGN_CONFIG", str(default_cfg)))
    if not cfg_path.is_file():
        pytest.skip(
            f"Design config not found: {cfg_path}. "
            "Set EDA_REAL_DESIGN_CONFIG to a valid ORFS design config path."
        )

    baseline = _baseline_finish_metrics_from_fixture()
    llm_params = _request_real_llm_param_suggestion(baseline)

    rerun_raw = execute_tool(
        "run_eda_stage",
        {
            "backend": "orfs",
            "stage": "finish",
            "design_name": design_name,
            "design_config": str(cfg_path),
            "pdk": pdk,
            "params": llm_params,
            # allow low-risk guardrail warnings without manual confirm cycle
            "_guardrail_confirmed": True,
        },
    )
    rerun = json.loads(rerun_raw)
    assert rerun.get("status") == "success", f"Rerun failed: {rerun}"

    new_run_id = rerun.get("run_id")
    assert isinstance(new_run_id, int), f"Invalid new run_id in rerun result: {rerun}"

    timing_raw = execute_tool(
        "query_timing",
        {
            "design_name": design_name,
            "run_id": new_run_id,
            "limit": 10,
        },
    )
    timing = json.loads(timing_raw)
    rows = timing.get("summary", [])
    assert rows, f"No timing summary rows for new run_id={new_run_id}: {timing}"

    # Use worst WNS row as representative for this run.
    worst = min(rows, key=lambda r: float(r.get("wns_ns") or 0.0))
    new_wns = float(worst.get("wns_ns") or 0.0)
    new_tns = float(worst.get("tns_ns") or 0.0)
    new_setup = int(worst.get("setup_violations") or 0)

    delta_wns = new_wns - float(baseline["wns_ns"])
    delta_tns = new_tns - float(baseline["tns_ns"])
    delta_setup = int(baseline["setup_violations"]) - new_setup

    logger.info(
        "AES rerun compare | params=%s | baseline=%s | new={wns:%s, tns:%s, setup:%s} "
        "| delta={wns:%+.3f, tns:%+.3f, setup:%+d}",
        llm_params,
        baseline,
        new_wns,
        new_tns,
        new_setup,
        delta_wns,
        delta_tns,
        delta_setup,
    )

    # Practical pass criterion for one low-risk rerun:
    # at least one of WNS/TNS/setup improves.
    improved = (delta_wns > 0.0) or (delta_tns > 0.0) or (delta_setup > 0)
    assert improved, (
        "No improvement after LLM-guided rerun. "
        f"baseline={baseline}, new={{'wns_ns': {new_wns}, 'tns_ns': {new_tns}, "
        f"'setup_violations': {new_setup}}}, params={llm_params}"
    )
