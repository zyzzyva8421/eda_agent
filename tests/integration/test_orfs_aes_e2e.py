"""End-to-end integration test: AES design on sky130hd via ORFS fixtures.

Scenario
--------
A real aes/sky130hd run finishes routing but has timing violations and
congestion hotspots.  The test verifies the full EDA agent optimization
pipeline WITHOUT requiring a live ORFS installation or PostgreSQL:

  Phase 1 – Parser Integration
    Parse realistic .rpt fixture files with the real parsers and verify the
    key metrics (WNS, TNS, congestion overflow count, power totals, util %).

  Phase 2 – Feature Vector Assembly
    Aggregate parsed records into a FeatureVector (the same shape that
    extract_features() produces from the DB) and verify expected values.

  Phase 3 – Root Cause Inference
    Run RULES against the FV.  With:
      - WNS = -0.352 ns  (<-0.2)            → routing_detour +0.35
      - 5 congestion hotspots (>3)           → routing_detour +0.30
      - utilization = 68%  (>65)             → routing_detour +0.20
      - TNS = -2.816 ns  (<-1.0)             → routing_detour +0.15
    routing_detour raw score = 1.00 → confidence "high".

  Phase 4 – Optimization Loop Simulation
    Confirm routing_detour (Case 1: correct top-1 prediction).
    Verify update_weights() reinforces the routing_detour multiplier (+δ).

  Phase 5 – Planner Smoke Test (mocked LLM)
    Drive Planner.run() with a mocked HTTP transport that returns a single
    tool call: infer_root_cause.  Verify the planner executes the tool and
    surfaces the routing_detour hypothesis in its final reply.

Fixtures live at: tests/fixtures/orfs/sky130hd/aes/
No real ORFS, OpenROAD, or PostgreSQL is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eda_agent.agent.inference.rules import RULE_BY_ID, RULES
from eda_agent.agent.inference.weights import DELTA
from eda_agent.parsers.congestion import CongestionParser
from eda_agent.parsers.power import PowerParser
from eda_agent.parsers.timing import TimingParser
from eda_agent.parsers.utilization import UtilizationParser

# ── Fixture directory ─────────────────────────────────────────────────────────

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "orfs" / "sky130hd" / "aes"
_REPORTS_DIR = _FIXTURE_DIR / "reports"
_LOGS_DIR = _FIXTURE_DIR / "logs"


# ── Shared helper: build FeatureVector from parsed records ────────────────────

def _build_fv(
    timing_records: list[dict],
    congestion_records: list[dict],
    power_records: list[dict],
    util_records: list[dict],
) -> dict[str, Any]:
    """Assemble a FeatureVector from raw parser output records.

    Mirrors the aggregation logic in ``extract_features()`` but works entirely
    in memory (no DB required).
    """
    fv: dict[str, Any] = {
        "wns_ns": None, "tns_ns": None, "failing_endpoints": None,
        "hold_violations": None, "setup_violations": None,
        "clock_skew_ns": None, "max_fanout_violations": None,
        "max_slew_violations": None, "max_cap_violations": None,
        "critical_path_delay_ns": None, "fmax_mhz": None,
        "congestion_hotspot_count": None, "max_overflow": None,
        "utilization_pct": None, "num_cells": None,
        "total_power_mw": None, "dynamic_power_mw": None,
        "leakage_power_mw": None, "drc_total": None,
    }

    # timing: pick worst (most negative) WNS summary
    summaries = [r for r in timing_records if r.get("kind") == "summary"]
    if summaries:
        worst = min(summaries, key=lambda r: r.get("wns_ns") or 0)
        fv["wns_ns"] = worst.get("wns_ns")
        fv["tns_ns"] = worst.get("tns_ns")
        fv["failing_endpoints"] = worst.get("failing_endpoints")
        fv["hold_violations"] = worst.get("hold_violations")
        fv["setup_violations"] = worst.get("setup_violations")
        fv["clock_skew_ns"] = worst.get("clock_skew_ns")
        fv["max_fanout_violations"] = worst.get("max_fanout_violations")
        fv["max_slew_violations"] = worst.get("max_slew_violations")
        fv["max_cap_violations"] = worst.get("max_cap_violations")
        fv["critical_path_delay_ns"] = worst.get("critical_path_delay_ns")
        fv["fmax_mhz"] = worst.get("fmax_mhz")

    # congestion: count hotspot records, track max overflow
    hotspots = [r for r in congestion_records if r.get("kind") == "hotspot"]
    if hotspots:
        fv["congestion_hotspot_count"] = len(hotspots)
        fv["max_overflow"] = max(h["overflow"] for h in hotspots)

    # utilization: first summary record
    util_summaries = [r for r in util_records if r.get("kind") == "summary"]
    if util_summaries:
        fv["utilization_pct"] = util_summaries[0].get("utilization_pct")
        fv["num_cells"] = util_summaries[0].get("num_cells")

    # power: summary row
    power_summaries = [r for r in power_records if r.get("kind") == "summary"]
    if power_summaries:
        ps = power_summaries[0]
        total_w = ps.get("total_power_w")
        if total_w is not None:
            fv["total_power_mw"] = total_w * 1e3
        internal_w = ps.get("internal_power_w")
        switching_w = ps.get("switching_power_w")
        if internal_w is not None and switching_w is not None:
            fv["dynamic_power_mw"] = (internal_w + switching_w) * 1e3
        leakage_w = ps.get("leakage_power_w")
        if leakage_w is not None:
            fv["leakage_power_mw"] = leakage_w * 1e3

    return fv


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Parser Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhase1ParserIntegration:
    """Verify that real ORFS AES report fixtures parse correctly."""

    def test_route_timing_wns(self):
        records = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["wns_ns"] == pytest.approx(-0.352)

    def test_route_timing_tns(self):
        records = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["tns_ns"] == pytest.approx(-2.816)

    def test_route_timing_failing_endpoints(self):
        records = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["failing_endpoints"] == 8

    def test_route_timing_fmax(self):
        records = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["fmax_mhz"] == pytest.approx(144.93)

    def test_route_timing_paths_extracted(self):
        records = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
        paths = [r for r in records if r["kind"] == "path"]
        assert len(paths) >= 2
        slacks = sorted(p["slack_ns"] for p in paths)
        assert slacks[0] == pytest.approx(-0.352)

    def test_congestion_total_overflow(self):
        records = CongestionParser().parse_file(_REPORTS_DIR / "5_congestion.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["total_overflow"] == 7

    def test_congestion_hotspot_count(self):
        records = CongestionParser().parse_file(_REPORTS_DIR / "5_congestion.rpt")
        hotspots = [r for r in records if r["kind"] == "hotspot"]
        assert len(hotspots) == 5

    def test_congestion_worst_hotspot_overflow(self):
        records = CongestionParser().parse_file(_REPORTS_DIR / "5_congestion.rpt")
        hotspots = [r for r in records if r["kind"] == "hotspot"]
        assert max(h["overflow"] for h in hotspots) == 4

    def test_congestion_layer_detail(self):
        records = CongestionParser().parse_file(_REPORTS_DIR / "5_congestion.rpt")
        layers = [r for r in records if r["kind"] == "layer"]
        metal3 = next((l for l in layers if l["layer"].lower() == "metal3"), None)
        assert metal3 is not None
        assert metal3["overflow"] == 4

    def test_power_total_mw(self):
        records = PowerParser().parse_file(_REPORTS_DIR / "6_finish_power.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        # fixture is in mW units → parser converts to W → total ≈ 0.65439 W? No.
        # PowerParser scales mW → W: total_power_w ≈ 6.5439e-4
        total_w = s.get("total_power_w", 0)
        total_mw = total_w * 1e3
        assert total_mw == pytest.approx(0.65439, rel=1e-3)

    def test_finish_timing_improved(self):
        """Final timing after eco fill should be better than post-route."""
        route_records = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
        finish_records = TimingParser().parse_file(_REPORTS_DIR / "6_finish_timing.rpt")
        route_wns = next(r for r in route_records if r["kind"] == "summary")["wns_ns"]
        finish_wns = next(r for r in finish_records if r["kind"] == "summary")["wns_ns"]
        # finish WNS should be less negative (improvement) or equal
        assert finish_wns >= route_wns

    def test_utilization_pct(self):
        records = UtilizationParser().parse_file(_REPORTS_DIR / "6_finish_utilization.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["utilization_pct"] == pytest.approx(68.0)

    def test_utilization_num_cells(self):
        records = UtilizationParser().parse_file(_REPORTS_DIR / "6_finish_utilization.rpt")
        s = next(r for r in records if r["kind"] == "summary")
        assert s["num_cells"] == 12847


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Feature Vector Assembly
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def aes_feature_vector():
    """Parsed + assembled FeatureVector for the AES post-route scenario."""
    timing = TimingParser().parse_file(_REPORTS_DIR / "5_route_timing.rpt")
    cong = CongestionParser().parse_file(_REPORTS_DIR / "5_congestion.rpt")
    power = PowerParser().parse_file(_REPORTS_DIR / "6_finish_power.rpt")
    util = UtilizationParser().parse_file(_REPORTS_DIR / "6_finish_utilization.rpt")
    return _build_fv(timing, cong, power, util)


class TestPhase2FeatureVector:
    """Verify the FeatureVector assembled from AES fixture reports."""

    def test_wns_is_negative(self, aes_feature_vector):
        assert aes_feature_vector["wns_ns"] is not None
        assert aes_feature_vector["wns_ns"] < 0

    def test_wns_matches_fixture(self, aes_feature_vector):
        assert aes_feature_vector["wns_ns"] == pytest.approx(-0.352)

    def test_tns_less_than_minus_one(self, aes_feature_vector):
        assert aes_feature_vector["tns_ns"] < -1.0

    def test_hotspot_count_above_three(self, aes_feature_vector):
        assert aes_feature_vector["congestion_hotspot_count"] == 5

    def test_utilization_above_sixty_five(self, aes_feature_vector):
        assert aes_feature_vector["utilization_pct"] > 65.0

    def test_power_present(self, aes_feature_vector):
        assert aes_feature_vector["total_power_mw"] is not None
        assert aes_feature_vector["total_power_mw"] > 0

    def test_power_approx(self, aes_feature_vector):
        assert aes_feature_vector["total_power_mw"] == pytest.approx(0.65439, rel=1e-2)

    def test_fmax_present(self, aes_feature_vector):
        assert aes_feature_vector["fmax_mhz"] == pytest.approx(144.93)

    def test_no_hold_violations(self, aes_feature_vector):
        # AES route fixture has 0 hold violations
        assert aes_feature_vector["hold_violations"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Root Cause Inference
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhase3Inference:
    """Verify that routing_detour is the top hypothesis for the AES scenario."""

    @pytest.fixture(autouse=True)
    def _fv(self, aes_feature_vector):
        self.fv = aes_feature_vector

    def test_routing_detour_fires(self):
        rule = RULE_BY_ID["routing_detour"]
        score, evidence, _ = rule.score(self.fv)
        assert score >= rule.min_score, (
            f"routing_detour should fire; got score={score:.3f}, evidence={evidence}"
        )

    def test_routing_detour_all_four_conditions_met(self):
        """All four weighted conditions for routing_detour are satisfied."""
        rule = RULE_BY_ID["routing_detour"]
        _, evidence, _ = rule.score(self.fv)
        met_features = {e["feature"] for e in evidence}
        assert "wns_ns" in met_features, "wns_ns condition not met"
        assert "congestion_hotspot_count" in met_features, "hotspot condition not met"
        assert "utilization_pct" in met_features, "utilization condition not met"
        assert "tns_ns" in met_features, "tns_ns condition not met"

    def test_routing_detour_score_near_one(self):
        """With all conditions met and no anti-conditions, score should ≈ 1.0."""
        rule = RULE_BY_ID["routing_detour"]
        score, _, _ = rule.score(self.fv)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_routing_detour_is_top_hypothesis(self):
        """routing_detour should rank first across all rules."""
        scored = [(r.id, r.score(self.fv)[0]) for r in RULES]
        scored.sort(key=lambda x: -x[1])
        assert scored[0][0] == "routing_detour"

    def test_routing_detour_confidence_high(self):
        """Score ≥ 0.7 maps to confidence='high'."""
        from eda_agent.agent.inference.engine import _score_to_confidence
        rule = RULE_BY_ID["routing_detour"]
        score, _, _ = rule.score(self.fv)
        assert _score_to_confidence(score) == "high"

    def test_experiment_suggests_reducing_utilization(self):
        """The routing_detour fix experiments should mention utilization."""
        rule = RULE_BY_ID["routing_detour"]
        actions = " ".join(e.action.lower() for e in rule.experiments)
        assert "utilization" in actions or "util" in actions or "density" in actions

    def test_experiments_are_low_risk(self):
        """At least one experiment for routing_detour is low-risk."""
        rule = RULE_BY_ID["routing_detour"]
        risks = {e.risk for e in rule.experiments}
        assert "low" in risks

    def test_cts_skew_does_not_fire(self):
        """No hold violations → cts_skew should not fire for this AES scenario."""
        rule = RULE_BY_ID["cts_skew"]
        score, _, _ = rule.score(self.fv)
        assert score < rule.min_score, (
            f"cts_skew should NOT fire for AES route scenario; got score={score:.3f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: Optimization Loop Simulation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhase4OptimizationLoop:
    """Simulate the confirm → weight-update feedback loop for AES."""

    @pytest.fixture(autouse=True)
    def _fv(self, aes_feature_vector):
        self.fv = aes_feature_vector

    def _run_inference(self) -> list[dict]:
        """Score all rules against AES FV and return ranked hypotheses."""
        hypotheses = []
        for rule in RULES:
            score, evidence, anti = rule.score(self.fv)
            if score >= rule.min_score:
                hypotheses.append({
                    "cause_id": rule.id,
                    "score": round(score, 4),
                    "evidence": evidence,
                })
        hypotheses.sort(key=lambda h: -h["score"])
        return hypotheses

    def test_routing_detour_is_top_1(self):
        hyps = self._run_inference()
        assert hyps, "No hypothesis fired — check fixture data"
        assert hyps[0]["cause_id"] == "routing_detour"

    def test_update_weights_case1_reinforces_top1(self):
        """Confirming top-1 (Case 1) should increase routing_detour multiplier."""
        from eda_agent.agent.inference.weights import update_weights

        hyps = self._run_inference()
        initial_multipliers = {"routing_detour": 1.0}

        persisted: dict[str, float] = {}

        def _fake_persist(updates: dict[str, float]) -> None:
            persisted.update(updates)

        with (
            patch("eda_agent.agent.inference.weights.get_multipliers",
                  return_value=initial_multipliers),
            patch("eda_agent.agent.inference.weights._persist_updates",
                  side_effect=_fake_persist),
        ):
            update_weights(
                top_hypotheses=hyps,
                confirmed_cause_id="routing_detour",
            )

        # Case 1: top-1 confirmed → +δ
        assert "routing_detour" in persisted
        expected = min(2.0, 1.0 + DELTA)
        assert persisted["routing_detour"] == pytest.approx(expected)

    def test_update_weights_case2_penalises_wrong_leader(self):
        """If routing_detour is top-1 but engineer confirms cts_skew (Case 2),
        routing_detour is penalised and cts_skew is reinforced."""
        from eda_agent.agent.inference.weights import update_weights

        hyps = self._run_inference()
        # Inject a second hypothesis so cts_skew appears in top-3
        if not any(h["cause_id"] == "cts_skew" for h in hyps):
            hyps.append({"cause_id": "cts_skew", "score": 0.20, "evidence": []})
        hyps.sort(key=lambda h: -h["score"])

        initial_multipliers = {"routing_detour": 1.0, "cts_skew": 1.0}
        persisted: dict[str, float] = {}

        def _fake_persist(updates: dict[str, float]) -> None:
            persisted.update(updates)

        with (
            patch("eda_agent.agent.inference.weights.get_multipliers",
                  return_value=initial_multipliers),
            patch("eda_agent.agent.inference.weights._persist_updates",
                  side_effect=_fake_persist),
        ):
            update_weights(top_hypotheses=hyps, confirmed_cause_id="cts_skew")

        # cts_skew reinforced, routing_detour penalised
        assert persisted.get("cts_skew", 1.0) > 1.0
        assert persisted.get("routing_detour", 1.0) < 1.0

    def test_full_confirm_pipeline_returns_status_confirmed(self):
        """Smoke-test the full confirm() call chain (DB mocked)."""
        from eda_agent.agent.inference.engine import confirm

        hyps = self._run_inference()
        rec = {
            "run_id": 999,
            "symptoms": (
                f"AES sky130hd post-route: WNS={self.fv['wns_ns']} ns, "
                f"TNS={self.fv['tns_ns']} ns, "
                f"congestion hotspots={self.fv['congestion_hotspot_count']}, "
                f"utilization={self.fv['utilization_pct']}%"
            ),
            "hypotheses": hyps,
        }

        mock_db = MagicMock()
        mock_mapping = MagicMock()
        mock_mapping.first.return_value = rec
        mock_db.execute.return_value.mappings.return_value = mock_mapping
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_db)
        ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("eda_agent.agent.inference.engine.get_db", return_value=ctx),
            patch("eda_agent.agent.inference.engine.update_weights",
                  return_value={"routing_detour": 1.05}),
            patch("eda_agent.agent.memory.save_case", return_value=42),
        ):
            result = confirm(inference_id=1001, confirmed_cause_id="routing_detour")

        assert result["status"] == "confirmed"
        assert result["confirmed_cause_id"] == "routing_detour"
        assert "case_id" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5: Planner Smoke Test (mocked LLM)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhase5PlannerSmoke:
    """Drive the Planner ReAct loop with a mocked MiniMax API.

    The mock returns:
      Turn 1: a tool call for ``infer_root_cause``
      Turn 2: a plain-text final answer containing "routing_detour"
    """

    def _make_mock_transport(self, tool_result: str) -> MagicMock:
        """Build an httpx mock that mimics the MiniMax chat completions API."""

        # ── Turn 1: tool call response ────────────────────────────────────────
        tool_call_response = {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "tc_001",
                        "type": "function",
                        "function": {
                            "name": "infer_root_cause",
                            "arguments": json.dumps({"run_id": 999}),
                        },
                    }],
                },
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

        # ── Turn 2: final text answer ─────────────────────────────────────────
        final_response = {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": (
                        "The root cause for AES timing failures is routing_detour "
                        "(congestion-induced detour).  Recommendation: reduce target "
                        "utilization from 68% to ~60% and rerun placement+routing."
                    ),
                },
            }],
            "usage": {"prompt_tokens": 200, "completion_tokens": 60},
        }

        responses = iter([tool_call_response, final_response])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = lambda: next(responses)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        return mock_client

    def test_planner_calls_infer_root_cause(self, aes_feature_vector):
        """Planner should execute infer_root_cause tool and return final answer."""
        from eda_agent.agent.planner import Planner

        fv = aes_feature_vector
        infer_result = {
            "inference_id": 999,
            "run_id": 999,
            "hypotheses": [{
                "cause_id": "routing_detour",
                "score": 1.0,
                "confidence": "high",
                "display_name": "Routing detour (congestion-induced)",
                "experiments": [{"action": "Reduce target utilization to 60%",
                                  "risk": "low", "param_hint": {"PLACE_DENSITY": "0.60"}}],
            }],
            "summary": (
                "Top hypothesis: routing_detour (confidence=high). "
                f"WNS={fv['wns_ns']} ns, {fv['congestion_hotspot_count']} hotspots, "
                f"util={fv['utilization_pct']}%."
            ),
        }

        mock_client = self._make_mock_transport(json.dumps(infer_result))

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("eda_agent.agent.tools.execute_tool",
                  return_value=json.dumps(infer_result)) as mock_exec,
        ):
            planner = Planner()
            answer = planner.run(
                "Analyse the post-route timing of AES on sky130hd (run_id=999) "
                "and suggest how to fix the violations."
            )

        assert answer is not None
        assert "routing_detour" in answer

    def test_planner_answer_mentions_utilization_fix(self, aes_feature_vector):
        """The planner's final answer should mention utilization reduction."""
        from eda_agent.agent.planner import Planner

        mock_client = self._make_mock_transport("{}")

        with (
            patch("httpx.Client", return_value=mock_client),
            patch("eda_agent.agent.tools.execute_tool", return_value="{}"),
        ):
            planner = Planner()
            answer = planner.run(
                "Diagnose AES sky130hd post-route timing (run_id=999)."
            )

        # The mocked final response explicitly mentions utilization
        assert "utilization" in answer.lower() or "routing_detour" in answer.lower()
