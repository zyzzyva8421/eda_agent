"""Real-LLM end-to-end integration tests using a local Ollama server.

This test suite makes **actual calls to the Ollama server** (or whichever
LLM is configured via ``LLM_BACKEND=ollama`` in the environment).  It is
designed to validate:

  * eda_agent's Planner correctly routes LLM calls to Ollama's
    OpenAI-compatible ``/v1/chat/completions`` endpoint.
  * The ``ollama`` backend selection logic in Planner.__init__ and
    _call_llm works end-to-end (URL construction, header injection).
  * The Ollama model responds to the AES diagnostic prompt with
    relevant content (tool calls or text).
  * Prompt-mode tool-calling parsing works with the Ollama response.

No PostgreSQL, no ORFS, no API keys are required — only a running
Ollama server with at least one model available.

Skipping condition
-----------------
All tests are skipped automatically when ``OLLAMA_BASE_URL`` is unreachable
or ``OLLAMA_MODEL`` is not set.  Run with::

    LLM_BACKEND=ollama pytest tests/integration/test_ollama_llm.py -v

to execute.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from eda_agent.config import settings

logger = logging.getLogger(__name__)

# ── Skip marker ───────────────────────────────────────────────────────────────


def _ollama_reachable() -> bool:
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{settings.ollama_base_url.rstrip('/')}/models")
        return r.status_code == 200
    except Exception:
        return False


_OLLAMA_AVAILABLE = (
    settings.llm_backend == "ollama"
    and settings.ollama_model not in ("", "dummy")
    and _ollama_reachable()
)

_skip_no_ollama = pytest.mark.skipif(
    not _OLLAMA_AVAILABLE,
    reason=(
        f"Ollama backend not available: "
        f"LLM_BACKEND={settings.llm_backend}, "
        f"OLLAMA_BASE_URL={settings.ollama_base_url}, "
        f"OLLAMA_MODEL={settings.ollama_model}. "
        f"Set LLM_BACKEND=ollama and ensure Ollama is running."
    ),
)

# ── AES fixture data (mirrored from test_orfs_aes_llm.py) ────────────────────

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


# ── Mock helpers ────────────────────────────────────────────────────────────────


def _patch_execute_tool():
    """Route tool calls to canned AES fixture responses (no DB / ORFS needed)."""
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
        return json.dumps({"error": f"Tool '{name}' not available in Ollama integration test"})
    return patch("eda_agent.agent.planner.execute_tool", side_effect=_fake_execute)


# ── Tests ────────────────────────────────────────────────────────────────────────


@_skip_no_ollama
def test_ollama_planner_backend_selects_ollama():
    """Planner must read LLM_BACKEND=ollama and set correct _base_url/_model."""
    from eda_agent.agent.planner import Planner

    planner = Planner()
    assert planner._base_url == settings.ollama_base_url.rstrip("/"), (
        f"Expected base URL {settings.ollama_base_url}, got {planner._base_url}"
    )
    assert planner._model == settings.ollama_model, (
        f"Expected model {settings.ollama_model}, got {planner._model}"
    )


@_skip_no_ollama
def test_ollama_planner_routes_to_correct_endpoint():
    """Planner._call_llm must POST to <ollama_base_url>/chat/completions."""
    from eda_agent.agent.planner import Planner
    from eda_agent.agent.memory import AgentMemory

    planner = Planner()  # max_iterations uses setting default (10)
    mem = AgentMemory()
    mem.add_user("Reply with exactly the word OK")

    resp = planner._call_llm(mem)
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    # Ollama should respond with something (model may hallucinate "OK")
    assert content, "Ollama returned empty response"
    logger.info("Ollama raw response: %s", content[:200])


@_skip_no_ollama
def test_ollama_react_loop_diagnoses_routing_detour():
    """The full ReAct loop must call infer_root_cause (or query_timing+infer).

    qwen2.5-coder:7b may not produce a high-quality final text answer in
    all cases; this test verifies *at least* one root-cause inference tool
    was called and the loop terminated without crashing.
    """
    from eda_agent.agent.planner import Planner

    called_tools: list[str] = []
    infer_args: list[dict] = []

    def _tracking_execute(name: str, arguments: dict[str, Any]) -> str:
        called_tools.append(name)
        if name == "infer_root_cause":
            infer_args.append(arguments)
            return json.dumps(_AES_INFER_RESULT)
        if name == "query_timing":
            return json.dumps({
                "run_id": arguments.get("run_id", 999), "design_name": "aes",
                "stage": "route", "wns_ns": -0.352, "tns_ns": -2.816,
                "failing_endpoints": 8, "hold_violations": 0, "fmax_mhz": 144.93,
                "clock_skew_ns": 0.045,
            })
        if name == "query_congestion":
            return json.dumps({"hotspot_count": 5, "max_overflow": 4})
        return json.dumps({"error": f"Tool '{name}' not available"})

    planner = Planner(max_iterations=6)
    with patch("eda_agent.agent.planner.execute_tool", side_effect=_tracking_execute):
        answer = planner.run(
            "I just finished routing the AES design on sky130hd (run_id=999). "
            "The flow completed but I suspect there are timing issues. "
            "Please diagnose the root cause of any PPA problems."
        )

    # Tool execution must have been attempted
    assert len(called_tools) > 0, f"No tools were called. Answer: {answer}"
    # infer_root_cause must have been called (the primary diagnostic tool)
    assert "infer_root_cause" in called_tools, (
        f"Expected infer_root_cause to be called. Called tools: {called_tools}"
    )
    # The infer call must carry the correct run_id
    assert any(a.get("run_id") == 999 for a in infer_args), (
        f"Expected run_id=999 in infer_root_cause call. Got: {infer_args}"
    )


@_skip_no_ollama
def test_ollama_react_loop_recommends_utilization_fix():
    """At least one tool must be called and the answer should mention utilization."""
    from eda_agent.agent.planner import Planner

    called_tools: list[str] = []

    def _tracking_execute(name: str, arguments: dict[str, Any]) -> str:
        called_tools.append(name)
        if name == "infer_root_cause":
            return json.dumps(_AES_INFER_RESULT)
        if name == "query_utilization":
            return json.dumps({"utilization_pct": 68.0, "num_cells": 12847})
        return json.dumps({"error": "not available"})

    planner = Planner(max_iterations=6)
    with patch("eda_agent.agent.planner.execute_tool", side_effect=_tracking_execute):
        answer = planner.run(
            "Analyse AES sky130hd post-route (run_id=999). "
            "The design has timing violations and I see congestion in metal3. "
            "What should I do to fix it?"
        )

    assert len(called_tools) > 0, f"No tools called. Answer: {answer}"
    # For this test we accept either a tool-call answer OR a free-text answer
    # that mentions the utilization fix (PLACE_DENSITY / utilization)
    answer_lower = answer.lower()
    mentions_fix = (
        "utilization" in answer_lower
        or "place_density" in answer_lower
        or "density" in answer_lower
        or "60%" in answer_lower
    )
    # If the model calls query_utilization, it is showing the right diagnostic path
    called_util_or_infer = "query_utilization" in called_tools or "infer_root_cause" in called_tools
    assert mentions_fix or called_util_or_infer, (
        f"Expected either utilization fix in answer or query_utilization tool call. "
        f"Called tools: {called_tools}, Answer:\n{answer}"
    )


@_skip_no_ollama
def test_ollama_react_loop_confirms_root_cause():
    """Planner must call confirm_root_cause when instructed."""
    from eda_agent.agent.memory import AgentMemory
    from eda_agent.agent.planner import Planner

    called_tools: list[str] = []
    confirm_args: list[dict] = []

    def _tracking_execute(name: str, arguments: dict[str, Any]) -> str:
        called_tools.append(name)
        if name == "infer_root_cause":
            return json.dumps(_AES_INFER_RESULT)
        if name == "confirm_root_cause":
            confirm_args.append(arguments)
            return json.dumps(_AES_CONFIRM_RESULT)
        return json.dumps({"error": "not available"})

    planner = Planner(max_iterations=6)
    mem = AgentMemory()
    with patch("eda_agent.agent.planner.execute_tool", side_effect=_tracking_execute):
        answer = planner.run(
            "I confirm routing_detour as the root cause for AES sky130hd "
            "(inference_id=999). Please record this confirmation.",
            memory=mem,
        )

    assert "confirm_root_cause" in called_tools, (
        f"Expected LLM to call confirm_root_cause. Called tools: {called_tools}"
    )
    assert len(confirm_args) > 0, "confirm_root_cause was called but with no arguments"
    first_confirm = confirm_args[0]
    assert first_confirm.get("inference_id") == 999 or first_confirm.get("confirmed_cause_id") == "routing_detour", (
        f"confirm_root_cause called with wrong args: {first_confirm}"
    )


@_skip_no_ollama
def test_ollama_explains_evidence():
    """At least one tool must be called — model may not free-text explain well."""
    from eda_agent.agent.planner import Planner

    called_tools: list[str] = []

    def _tracking_execute(name: str, arguments: dict[str, Any]) -> str:
        called_tools.append(name)
        if name == "infer_root_cause":
            return json.dumps(_AES_INFER_RESULT)
        if name == "query_timing":
            return json.dumps({"wns_ns": -0.352, "tns_ns": -2.816})
        if name == "query_congestion":
            return json.dumps({"hotspot_count": 5, "max_overflow": 4})
        return json.dumps({"error": "not available"})

    planner = Planner(max_iterations=6)
    with patch("eda_agent.agent.planner.execute_tool", side_effect=_tracking_execute):
        answer = planner.run(
            "Run root cause inference for AES sky130hd (run_id=999) and "
            "explain *why* you chose the top hypothesis, listing specific metrics."
        )

    # At least infer_root_cause must have been called — qwen2.5-coder may not
    # produce a free-text explanation before exhausting iterations.
    assert "infer_root_cause" in called_tools, (
        f"Expected infer_root_cause to be called. Called tools: {called_tools}"
    )


@_skip_no_ollama
def test_ollama_api_direct_call():
    """Call the Ollama /v1/chat/completions endpoint directly (one-shot, no ReAct)."""
    prompt = (
        "You are an EDA expert. Summarise the following root-cause inference result "
        "in exactly 3 sentences: (1) root cause, (2) evidence, (3) recommended fix.\n\n"
        f"```json\n{json.dumps(_AES_INFER_RESULT, indent=2, ensure_ascii=False)}\n```"
    )
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": "You are an expert EDA physical design assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }
    url = f"{settings.ollama_base_url.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload)
    assert resp.status_code == 200, f"Ollama API returned {resp.status_code}: {resp.text[:200]}"

    data = resp.json()
    answer = data["choices"][0]["message"]["content"]
    assert answer and len(answer) > 20, "Ollama returned empty or trivial answer"
    logger.info("Ollama direct-call summary:\n%s", answer)

    answer_lower = answer.lower()
    assert "routing_detour" in answer_lower or "routing detour" in answer_lower, (
        f"Expected answer to name routing_detour. Answer:\n{answer}"
    )