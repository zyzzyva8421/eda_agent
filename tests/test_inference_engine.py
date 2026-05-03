"""Tests for eda_agent.agent.inference.engine.

DB calls, feature extraction, and weight management are mocked so no
PostgreSQL connection is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eda_agent.agent.inference.engine import (
    _build_next_action,
    _build_summary,
    _score_to_confidence,
    confirm,
    infer,
)


# ── _score_to_confidence ──────────────────────────────────────────────────────


@pytest.mark.parametrize("score,expected", [
    (0.9, "high"),
    (0.65, "high"),
    (0.64, "medium"),
    (0.5, "medium"),
    (0.35, "medium"),
    (0.34, "low"),
    (0.0, "low"),
])
def test_score_to_confidence(score, expected):
    assert _score_to_confidence(score) == expected


# ── _build_summary ────────────────────────────────────────────────────────────


def test_build_summary_empty():
    assert "No significant" in _build_summary([])


def test_build_summary_single():
    hyps = [{"display_name": "Routing detour", "confidence": "high", "score": 0.85}]
    summary = _build_summary(hyps)
    assert "Routing detour" in summary
    assert "high" in summary
    assert "0.85" in summary


def test_build_summary_multiple():
    hyps = [
        {"display_name": "Routing detour", "confidence": "high", "score": 0.85},
        {"display_name": "CTS skew", "confidence": "medium", "score": 0.55},
    ]
    summary = _build_summary(hyps)
    assert "Routing detour" in summary
    assert "CTS skew" in summary


# ── _build_next_action ────────────────────────────────────────────────────────


def test_build_next_action_empty():
    action = _build_next_action([])
    assert len(action) > 0  # always returns some advice


def test_build_next_action_prefers_low_risk():
    hyps = [{
        "experiments": [
            {"action": "Risky change", "risk": "high", "param_hint": {}},
            {"action": "Safe change", "risk": "low", "param_hint": {}},
        ]
    }]
    action = _build_next_action(hyps)
    assert "Safe change" in action


def test_build_next_action_falls_back_to_any_risk():
    hyps = [{
        "experiments": [
            {"action": "Only medium risk", "risk": "medium", "param_hint": {}},
        ]
    }]
    action = _build_next_action(hyps)
    assert "Only medium risk" in action


def test_build_next_action_with_param_hint():
    hyps = [{
        "experiments": [
            {"action": "Reduce utilization", "risk": "low",
             "param_hint": {"CORE_UTILIZATION": "-5%"}},
        ]
    }]
    action = _build_next_action(hyps)
    assert "CORE_UTILIZATION" in action


def test_build_next_action_no_experiments():
    hyps = [{"experiments": []}]
    action = _build_next_action(hyps)
    assert len(action) > 0


# ── infer() ───────────────────────────────────────────────────────────────────


def _congested_feature_vector():
    """Feature vector that triggers routing_detour with high score."""
    return {
        "wns_ns": -0.5,
        "tns_ns": -8.0,
        "failing_endpoints": 7,
        "hold_violations": 0,
        "setup_violations": 7,
        "clock_skew_ns": 0.02,
        "max_fanout_violations": 0,
        "max_slew_violations": 0,
        "max_cap_violations": 0,
        "critical_path_delay_ns": 4.5,
        "fmax_mhz": 220.0,
        "congestion_hotspot_count": 6,
        "max_overflow": 2.0,
        "utilization_pct": 78.0,
        "num_cells": 50000,
        "total_power_mw": 120.0,
        "dynamic_power_mw": 90.0,
        "leakage_power_mw": 30.0,
        "drc_total": 12,
    }


def _mock_db_save(inference_id: int = 42):
    """Return a mock get_db context that returns *inference_id* on INSERT."""
    mock_row = MagicMock()
    mock_row.__getitem__ = MagicMock(return_value=inference_id)
    mock_db = MagicMock()
    mock_db.execute.return_value.first.return_value = mock_row
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestInfer:
    def _call_infer(self, fv, inference_id=42):
        with (
            patch("eda_agent.agent.inference.engine.extract_features", return_value=fv),
            patch("eda_agent.agent.inference.engine.get_multipliers", return_value={}),
            patch("eda_agent.agent.inference.engine.get_db", return_value=_mock_db_save(inference_id)),
        ):
            return infer(run_id=100, symptoms="wns bad, congestion hotspots")

    def test_returns_required_keys(self):
        result = self._call_infer(_congested_feature_vector())
        for key in ("inference_id", "run_id", "features", "hypotheses",
                    "summary", "next_action"):
            assert key in result, f"Missing key: {key}"

    def test_run_id_preserved(self):
        result = self._call_infer(_congested_feature_vector())
        assert result["run_id"] == 100

    def test_features_preserved(self):
        fv = _congested_feature_vector()
        result = self._call_infer(fv)
        assert result["features"]["wns_ns"] == fv["wns_ns"]

    def test_hypotheses_ranked_descending(self):
        result = self._call_infer(_congested_feature_vector())
        scores = [h["score"] for h in result["hypotheses"]]
        assert scores == sorted(scores, reverse=True)

    def test_at_most_3_hypotheses(self):
        result = self._call_infer(_congested_feature_vector())
        assert len(result["hypotheses"]) <= 3

    def test_hypothesis_structure(self):
        result = self._call_infer(_congested_feature_vector())
        assert len(result["hypotheses"]) > 0
        h = result["hypotheses"][0]
        for field in ("rank", "cause_id", "display_name", "score",
                      "confidence", "evidence", "experiments"):
            assert field in h, f"Hypothesis missing field: {field}"

    def test_congested_fv_fires_routing_detour(self):
        result = self._call_infer(_congested_feature_vector())
        cause_ids = [h["cause_id"] for h in result["hypotheses"]]
        assert "routing_detour" in cause_ids

    def test_routing_detour_is_top1_for_congested(self):
        result = self._call_infer(_congested_feature_vector())
        assert result["hypotheses"][0]["cause_id"] == "routing_detour"

    def test_multiplier_applied(self):
        """Boosting cts_skew multiplier should push it higher in ranking."""
        fv = {**_congested_feature_vector(),
              "hold_violations": 5, "clock_skew_ns": 0.12, "setup_violations": 2}
        with (
            patch("eda_agent.agent.inference.engine.extract_features", return_value=fv),
            patch("eda_agent.agent.inference.engine.get_multipliers",
                  return_value={"cts_skew": 2.0, "routing_detour": 0.3}),
            patch("eda_agent.agent.inference.engine.get_db",
                  return_value=_mock_db_save()),
        ):
            result = infer(run_id=1)
        cause_ids = [h["cause_id"] for h in result["hypotheses"]]
        # With cts_skew boosted and routing_detour penalised, cts_skew should rank
        assert "cts_skew" in cause_ids

    def test_db_failure_returns_inference_id_minus1(self):
        """DB save failure should not crash infer(); inference_id = -1."""
        with (
            patch("eda_agent.agent.inference.engine.extract_features",
                  return_value=_congested_feature_vector()),
            patch("eda_agent.agent.inference.engine.get_multipliers", return_value={}),
            patch("eda_agent.agent.inference.engine.get_db",
                  side_effect=Exception("DB down")),
        ):
            result = infer(run_id=1)
        assert result["inference_id"] == -1
        assert len(result["hypotheses"]) > 0  # still returns hypotheses

    def test_no_data_fv_returns_empty_hypotheses(self):
        empty_fv = {k: None for k in _congested_feature_vector()}
        result = self._call_infer(empty_fv)
        assert result["hypotheses"] == []
        assert "No significant" in result["summary"]

    def test_summary_non_empty(self):
        result = self._call_infer(_congested_feature_vector())
        assert len(result["summary"]) > 0

    def test_next_action_non_empty(self):
        result = self._call_infer(_congested_feature_vector())
        assert len(result["next_action"]) > 0


# ── confirm() ─────────────────────────────────────────────────────────────────


def _mock_confirm_db(rec: dict | None):
    """Mock get_db so UPDATE succeeds and SELECT returns *rec*.

    confirm() opens get_db() twice: once for UPDATE+SELECT, once for design lookup.
    Both calls are intercepted via the canonical patch target.
    """
    mock_db = MagicMock()
    # First execute = UPDATE (no meaningful return)
    # Second execute = SELECT root_cause_inferences → returns rec via mappings().first()
    # Third execute = design lookup → returns None (design info optional)
    mock_mapping = MagicMock()
    mock_mapping.first.return_value = rec
    mock_db.execute.return_value.mappings.return_value = mock_mapping

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# save_case is imported locally inside confirm(); patch at its canonical location.
_PATCH_SAVE_CASE = "eda_agent.agent.memory.save_case"
# get_db is imported at engine module level; patch the reference there, not the source.
_PATCH_CONFIRM_DB = "eda_agent.agent.inference.engine.get_db"


class TestConfirm:
    def test_returns_status_confirmed(self):
        rec = {
            "run_id": 100,
            "symptoms": "wns bad",
            "hypotheses": [
                {"cause_id": "routing_detour", "score": 0.9, "experiments":
                 [{"action": "Reduce utilization", "risk": "low"}]}
            ],
        }
        with (
            patch(_PATCH_CONFIRM_DB, return_value=_mock_confirm_db(rec)),
            patch("eda_agent.agent.inference.engine.update_weights",
                  return_value={"routing_detour": 1.05}),
            patch(_PATCH_SAVE_CASE, return_value=7),
        ):
            result = confirm(inference_id=42, confirmed_cause_id="routing_detour")
        assert result["status"] == "confirmed"
        assert result["inference_id"] == 42

    def test_confirm_calls_update_weights(self):
        rec = {
            "run_id": 100,
            "symptoms": "",
            "hypotheses": [{"cause_id": "routing_detour", "score": 0.9, "experiments": []}],
        }
        mock_update = MagicMock(return_value={})
        with (
            patch(_PATCH_CONFIRM_DB, return_value=_mock_confirm_db(rec)),
            patch("eda_agent.agent.inference.engine.update_weights", mock_update),
            patch(_PATCH_SAVE_CASE, return_value=1),
        ):
            confirm(inference_id=1, confirmed_cause_id="routing_detour")
        mock_update.assert_called_once()

    def test_confirm_calls_save_case(self):
        rec = {
            "run_id": 100,
            "symptoms": "wns",
            "hypotheses": [{"cause_id": "cts_skew", "score": 0.8, "experiments": []}],
        }
        mock_save = MagicMock(return_value=5)
        with (
            patch(_PATCH_CONFIRM_DB, return_value=_mock_confirm_db(rec)),
            patch("eda_agent.agent.inference.engine.update_weights", return_value={}),
            patch(_PATCH_SAVE_CASE, mock_save),
        ):
            confirm(inference_id=1, confirmed_cause_id="cts_skew")
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        # symptoms should be passed
        assert "wns" in str(call_kwargs)

    def test_confirm_db_failure_returns_error(self):
        with patch(_PATCH_CONFIRM_DB, side_effect=Exception("DB down")):
            result = confirm(inference_id=1, confirmed_cause_id="routing_detour")
        # confirm() catches Exception and returns {"status": "error", ...}
        assert result.get("status") == "error"

    def test_confirm_unknown_cause_id_uses_raw_string(self):
        rec = {
            "run_id": 100,
            "symptoms": "",
            "hypotheses": [],
        }
        mock_save = MagicMock(return_value=1)
        with (
            patch(_PATCH_CONFIRM_DB, return_value=_mock_confirm_db(rec)),
            patch("eda_agent.agent.inference.engine.update_weights", return_value={}),
            patch(_PATCH_SAVE_CASE, mock_save),
        ):
            result = confirm(inference_id=1, confirmed_cause_id="custom_cause_xyz")
        assert result["status"] == "confirmed"
        # The raw string should be used as root_cause when no RULE_BY_ID match
        call_kwargs = mock_save.call_args
        assert "custom_cause_xyz" in str(call_kwargs)
