"""Tests for eda_agent.agent.inference.weights (Phase B feedback learning).

All DB calls are mocked so no PostgreSQL connection is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eda_agent.agent.inference.weights import (
    DELTA,
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    _clamp,
    get_multipliers,
    update_weights,
)

# ── _clamp ────────────────────────────────────────────────────────────────────


def test_clamp_within_range():
    assert _clamp(1.0) == pytest.approx(1.0)
    assert _clamp(0.5) == pytest.approx(0.5)


def test_clamp_lower_bound():
    assert _clamp(0.0) == pytest.approx(MIN_MULTIPLIER)
    assert _clamp(-5.0) == pytest.approx(MIN_MULTIPLIER)


def test_clamp_upper_bound():
    assert _clamp(3.0) == pytest.approx(MAX_MULTIPLIER)
    assert _clamp(999.0) == pytest.approx(MAX_MULTIPLIER)


def test_clamp_at_exact_bounds():
    assert _clamp(MIN_MULTIPLIER) == pytest.approx(MIN_MULTIPLIER)
    assert _clamp(MAX_MULTIPLIER) == pytest.approx(MAX_MULTIPLIER)


# ── get_multipliers ───────────────────────────────────────────────────────────


def test_get_multipliers_returns_dict_from_db():
    mock_rows = [("routing_detour", 1.2), ("cts_skew", 0.8)]
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchall.return_value = mock_rows

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch("eda_agent.agent.inference.weights.get_db", return_value=ctx):
        result = get_multipliers()

    assert result == {"routing_detour": 1.2, "cts_skew": 0.8}


def test_get_multipliers_db_failure_returns_empty():
    with patch("eda_agent.agent.inference.weights.get_db", side_effect=Exception("DB down")):
        result = get_multipliers()
    assert result == {}


def test_get_multipliers_empty_table():
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchall.return_value = []

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch("eda_agent.agent.inference.weights.get_db", return_value=ctx):
        result = get_multipliers()
    assert result == {}


def test_persist_updates_falls_back_without_on_conflict_support():
    mock_db = MagicMock()
    update_result = MagicMock()
    update_result.rowcount = 0
    mock_db.execute.side_effect = [update_result, None]

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch("eda_agent.agent.inference.weights.get_db", return_value=ctx),
        patch(
            "eda_agent.agent.inference.weights.supports_postgresql_on_conflict",
            return_value=False,
        ),
    ):
        from eda_agent.agent.inference.weights import _persist_updates

        _persist_updates({"routing_detour": 1.2})

    assert mock_db.execute.call_count == 2
    assert "UPDATE rule_weights" in str(mock_db.execute.call_args_list[0].args[0])
    assert "INSERT INTO rule_weights" in str(mock_db.execute.call_args_list[1].args[0])


# ── update_weights – 3 learning cases ────────────────────────────────────────


def _make_hypothesis(cause_id: str, score: float = 0.8) -> dict:
    return {"cause_id": cause_id, "score": score}


def _patch_weights(current: dict):
    """Return a context manager that makes get_multipliers return *current*
    and silences _persist_updates."""
    return (
        patch("eda_agent.agent.inference.weights.get_multipliers", return_value=current),
        patch("eda_agent.agent.inference.weights._persist_updates"),
    )


class TestUpdateWeightsCase1:
    """Confirmed cause IS top-1 → boost it."""

    def test_top1_correct_boosts_top1(self):
        current = {"routing_detour": 1.0}
        hyps = [_make_hypothesis("routing_detour")]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("routing_detour", hyps)
        assert result["routing_detour"] == pytest.approx(1.0 + DELTA)

    def test_top1_correct_only_updates_one_rule(self):
        current = {"routing_detour": 1.0, "cts_skew": 1.0}
        hyps = [_make_hypothesis("routing_detour")]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("routing_detour", hyps)
        assert "cts_skew" not in result


class TestUpdateWeightsCase2:
    """Confirmed is in top-3 but NOT top-1."""

    def test_correct_boosted_top1_penalised(self):
        current = {"cts_skew": 1.0, "routing_detour": 1.0}
        hyps = [
            _make_hypothesis("routing_detour"),   # top-1 (wrong)
            _make_hypothesis("cts_skew"),          # top-2 (correct)
        ]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("cts_skew", hyps)
        assert result["cts_skew"] == pytest.approx(1.0 + DELTA)
        assert result["routing_detour"] == pytest.approx(1.0 - DELTA)

    def test_third_place_boosted(self):
        current = {"density_saturation": 1.0, "routing_detour": 1.0}
        hyps = [
            _make_hypothesis("routing_detour"),
            _make_hypothesis("cts_skew"),
            _make_hypothesis("density_saturation"),
        ]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("density_saturation", hyps)
        assert result["density_saturation"] == pytest.approx(1.0 + DELTA)
        assert result["routing_detour"] == pytest.approx(1.0 - DELTA)


class TestUpdateWeightsCase3:
    """Confirmed NOT in top-3 at all."""

    def test_confirmed_boosted_all_top_penalised(self):
        current = {
            "routing_detour": 1.0,
            "cts_skew": 1.0,
            "over_buffering": 1.0,
            "hold_margin_tight": 1.0,
        }
        hyps = [
            _make_hypothesis("routing_detour"),
            _make_hypothesis("cts_skew"),
            _make_hypothesis("over_buffering"),
        ]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("hold_margin_tight", hyps)
        assert result["hold_margin_tight"] == pytest.approx(1.0 + DELTA)
        for rule_id in ["routing_detour", "cts_skew", "over_buffering"]:
            assert result[rule_id] == pytest.approx(1.0 - DELTA / 2)

    def test_unknown_rule_confirmed_uses_default_1(self):
        """Confirmed cause not in DB yet → base defaults to 1.0."""
        current = {"routing_detour": 1.0}
        hyps = [_make_hypothesis("routing_detour")]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("brand_new_rule", hyps)
        # brand_new_rule not in top-3, so case-3 fires
        assert result["brand_new_rule"] == pytest.approx(1.0 + DELTA)


class TestUpdateWeightsBoundary:
    def test_multiplier_clamped_at_max(self):
        current = {"routing_detour": MAX_MULTIPLIER}
        hyps = [_make_hypothesis("routing_detour")]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("routing_detour", hyps)
        assert result["routing_detour"] == pytest.approx(MAX_MULTIPLIER)

    def test_multiplier_clamped_at_min(self):
        current = {"routing_detour": MIN_MULTIPLIER, "cts_skew": MIN_MULTIPLIER}
        hyps = [_make_hypothesis("routing_detour"), _make_hypothesis("cts_skew")]
        # Case 2: routing_detour (top-1) penalised
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("cts_skew", hyps)
        assert result["routing_detour"] >= MIN_MULTIPLIER

    def test_empty_top_hypotheses_boosts_confirmed(self):
        """No prior hypotheses → just boost the confirmed cause."""
        current = {}
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("routing_detour", [])
        assert result["routing_detour"] == pytest.approx(1.0 + DELTA)

    def test_custom_delta(self):
        current = {"routing_detour": 1.0}
        hyps = [_make_hypothesis("routing_detour")]
        p1, p2 = _patch_weights(current)
        with p1, p2:
            result = update_weights("routing_detour", hyps, delta=0.10)
        assert result["routing_detour"] == pytest.approx(1.10)
