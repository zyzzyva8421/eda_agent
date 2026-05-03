"""Tests for eda_agent.agent.inference.rules.

All tests are pure (no DB / LLM required).
"""

from __future__ import annotations

import pytest

from eda_agent.agent.inference.rules import (
    RULE_BY_ID,
    RULES,
    Condition,
    ExperimentSuggestion,
    Rule,
)


# ── Condition ─────────────────────────────────────────────────────────────────


class TestCondition:
    @pytest.mark.parametrize("op,val,threshold,expected", [
        (">",  5.0, 4.0, True),
        (">",  4.0, 4.0, False),
        (">=", 4.0, 4.0, True),
        ("<",  3.0, 4.0, True),
        ("<",  4.0, 4.0, False),
        ("<=", 4.0, 4.0, True),
        ("!=", 5.0, 4.0, True),
        ("!=", 4.0, 4.0, False),
    ])
    def test_operators(self, op, val, threshold, expected):
        c = Condition(feature="x", op=op, threshold=threshold)
        assert c.evaluate({"x": val}) == expected

    def test_missing_feature_returns_false(self):
        c = Condition(feature="missing", op=">", threshold=0.0)
        assert c.evaluate({}) is False
        assert c.evaluate({"other": 99}) is False

    def test_none_value_returns_false(self):
        c = Condition(feature="x", op=">", threshold=0.0)
        assert c.evaluate({"x": None}) is False

    def test_unknown_operator_raises(self):
        c = Condition(feature="x", op="??", threshold=0.0)
        with pytest.raises(ValueError, match="Unknown operator"):
            c.evaluate({"x": 1.0})

    def test_to_dict_met(self):
        c = Condition(feature="wns_ns", op="<", threshold=-0.2, weight=0.35)
        d = c.to_dict({"wns_ns": -0.5})
        assert d["met"] is True
        assert d["actual"] == -0.5
        assert d["feature"] == "wns_ns"
        assert d["weight"] == 0.35

    def test_to_dict_not_met(self):
        c = Condition(feature="wns_ns", op="<", threshold=-0.2)
        d = c.to_dict({"wns_ns": 0.1})
        assert d["met"] is False


# ── Rule.score() ──────────────────────────────────────────────────────────────


class TestRuleScore:
    def _make_rule(self, conditions, anti_conditions=None, min_score=0.0):
        return Rule(
            id="test_rule",
            display_name="Test",
            description="test",
            conditions=conditions,
            anti_conditions=anti_conditions or [],
            min_score=min_score,
        )

    def test_all_conditions_met_score_1(self):
        rule = self._make_rule([
            Condition("a", ">", 0.0, weight=1.0),
            Condition("b", ">", 0.0, weight=1.0),
        ])
        score, evidence, anti = rule.score({"a": 1.0, "b": 1.0})
        assert score == pytest.approx(1.0)
        assert len(evidence) == 2
        assert anti == []

    def test_no_conditions_met_score_0(self):
        rule = self._make_rule([
            Condition("a", ">", 10.0, weight=1.0),
        ])
        score, evidence, anti = rule.score({"a": 0.0})
        assert score == pytest.approx(0.0)
        assert evidence == []

    def test_partial_conditions_weighted(self):
        rule = self._make_rule([
            Condition("a", ">", 0.0, weight=0.75),  # met
            Condition("b", ">", 0.0, weight=0.25),  # not met
        ])
        score, evidence, anti = rule.score({"a": 1.0, "b": -1.0})
        assert score == pytest.approx(0.75)
        assert len(evidence) == 1

    def test_anti_condition_reduces_score(self):
        rule = self._make_rule(
            conditions=[Condition("a", ">", 0.0, weight=1.0)],
            anti_conditions=[Condition("bad", ">", 0.0, weight=0.3)],
        )
        score, _, anti = rule.score({"a": 1.0, "bad": 1.0})
        assert score == pytest.approx(0.7)
        assert len(anti) == 1

    def test_score_clamped_to_zero_with_penalty(self):
        rule = self._make_rule(
            conditions=[Condition("a", ">", 0.0, weight=1.0)],
            anti_conditions=[Condition("bad", ">", 0.0, weight=2.0)],
        )
        score, _, _ = rule.score({"a": 1.0, "bad": 1.0})
        assert score >= 0.0   # never negative

    def test_empty_conditions_no_crash(self):
        """A rule with no conditions should not raise."""
        rule = self._make_rule([])
        score, evidence, anti = rule.score({"a": 1.0})
        assert score == pytest.approx(0.0)

    def test_evidence_tracks_only_met_conditions(self):
        rule = self._make_rule([
            Condition("x", ">", 0.0),
            Condition("y", ">", 100.0),
        ])
        _, evidence, _ = rule.score({"x": 1.0, "y": 0.0})
        assert len(evidence) == 1
        assert evidence[0]["feature"] == "x"


# ── Built-in rule catalogue ───────────────────────────────────────────────────


class TestBuiltinRules:
    def test_rule_count(self):
        assert len(RULES) >= 5

    def test_rule_ids_unique(self):
        ids = [r.id for r in RULES]
        assert len(ids) == len(set(ids))

    def test_rule_by_id_contains_all(self):
        for rule in RULES:
            assert rule.id in RULE_BY_ID
            assert RULE_BY_ID[rule.id] is rule

    def test_all_rules_have_display_name(self):
        for rule in RULES:
            assert rule.display_name, f"Rule {rule.id} missing display_name"

    def test_all_rules_have_conditions(self):
        for rule in RULES:
            assert rule.conditions, f"Rule {rule.id} has no conditions"

    def test_all_rules_have_experiments(self):
        for rule in RULES:
            assert rule.experiments, f"Rule {rule.id} has no experiments"

    def test_all_experiments_have_risk(self):
        valid_risks = {"low", "medium", "high"}
        for rule in RULES:
            for exp in rule.experiments:
                assert exp.risk in valid_risks, (
                    f"Rule {rule.id} experiment '{exp.action}' has invalid risk '{exp.risk}'"
                )


# ── routing_detour – targeted scenario tests ─────────────────────────────────


class TestRoutingDetourRule:
    def _fv_congested(self) -> dict:
        return {
            "wns_ns": -0.5,
            "congestion_hotspot_count": 5,
            "utilization_pct": 72.0,
            "tns_ns": -8.0,
            "hold_violations": 0,
        }

    def test_fully_congested_fires_above_threshold(self):
        rule = RULE_BY_ID["routing_detour"]
        score, _, _ = rule.score(self._fv_congested())
        assert score >= rule.min_score

    def test_all_conditions_met_score_near_1(self):
        rule = RULE_BY_ID["routing_detour"]
        fv = {"wns_ns": -1.0, "congestion_hotspot_count": 10,
               "utilization_pct": 80.0, "tns_ns": -5.0, "hold_violations": 0}
        score, _, _ = rule.score(fv)
        assert score >= 0.9

    def test_no_congestion_does_not_fire(self):
        # routing_detour conditions: wns < -0.2 (w=0.35), hotspots>3 (w=0.30),
        # util>65 (w=0.20), tns < -1.0 (w=0.15).
        # With wns=0.1 and all others missing, no conditions are met → score=0.
        rule = RULE_BY_ID["routing_detour"]
        fv = {"wns_ns": 0.1, "congestion_hotspot_count": 0,
               "utilization_pct": 45.0, "tns_ns": -0.1, "hold_violations": 0}
        score, _, _ = rule.score(fv)
        assert score < rule.min_score

    def test_hold_violations_reduce_score(self):
        rule = RULE_BY_ID["routing_detour"]
        fv_with = {**self._fv_congested(), "hold_violations": 15}
        fv_without = {**self._fv_congested(), "hold_violations": 0}
        score_with, _, _ = rule.score(fv_with)
        score_without, _, _ = rule.score(fv_without)
        assert score_with < score_without


# ── cts_skew – targeted scenario tests ───────────────────────────────────────


class TestCtsSkewRule:
    def test_cts_skew_fires_on_hold_and_skew(self):
        rule = RULE_BY_ID["cts_skew"]
        fv = {"hold_violations": 5, "clock_skew_ns": 0.12, "setup_violations": 2,
               "wns_ns": -0.1}
        score, _, _ = rule.score(fv)
        assert score >= rule.min_score

    def test_no_hold_violations_does_not_fire(self):
        # cts_skew conditions: hold>0 (w=0.40), skew>0.08 (w=0.40), setup<5 (w=0.20)
        # With hold=0 and skew=0.02 (below threshold), only setup<5 met → 0.20/1.0=0.20
        rule = RULE_BY_ID["cts_skew"]
        fv = {"hold_violations": 0, "clock_skew_ns": 0.02, "setup_violations": 0,
               "wns_ns": 0.0}
        score, _, _ = rule.score(fv)
        assert score < rule.min_score


# ── ExperimentSuggestion ──────────────────────────────────────────────────────


def test_experiment_to_dict():
    exp = ExperimentSuggestion(
        action="Reduce utilization",
        risk="low",
        param_hint={"CORE_UTILIZATION": "-5%"},
    )
    d = exp.to_dict()
    assert d["action"] == "Reduce utilization"
    assert d["risk"] == "low"
    assert d["param_hint"] == {"CORE_UTILIZATION": "-5%"}


def test_experiment_empty_param_hint():
    exp = ExperimentSuggestion(action="Check timing", risk="medium")
    d = exp.to_dict()
    assert d["param_hint"] == {}
