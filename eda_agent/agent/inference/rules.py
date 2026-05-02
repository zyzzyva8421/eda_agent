"""Rule definitions for the Root Cause Inference Engine – Phase A.

Each :class:`Rule` declares:
- *conditions* that contribute positive evidence (weighted)
- *anti_conditions* that reduce the score (penalties)
- *experiments* – safe, low-risk actions to confirm or fix the cause

Scoring formula per rule::

    raw = Σ(w_i * met_i) / Σ(w_i)   ∈ [0, 1]
    penalty = Σ(p_j * anti_j)
    score = max(0, raw - penalty)

``score`` is then normalised across all fired rules to produce ``confidence``:
    ≥ 0.7  → "high"
    ≥ 0.4  → "medium"
    < 0.4  → "low"
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Any, Callable

# ── Condition helpers ─────────────────────────────────────────────────────────

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "!=": operator.ne,
}


@dataclass(frozen=True)
class Condition:
    """A single numeric threshold check on a FeatureVector key."""

    feature: str
    op: str        # one of ">", ">=", "<", "<=", "!="
    threshold: float
    weight: float = 1.0  # contribution weight when met

    def evaluate(self, fv: dict[str, Any]) -> bool:
        val = fv.get(self.feature)
        if val is None:
            return False
        fn = _OPS.get(self.op)
        if fn is None:
            raise ValueError(f"Unknown operator: {self.op}")
        return fn(float(val), self.threshold)

    def to_dict(self, fv: dict[str, Any]) -> dict[str, Any]:
        val = fv.get(self.feature)
        met = self.evaluate(fv)
        return {
            "feature": self.feature,
            "op": self.op,
            "threshold": self.threshold,
            "actual": val,
            "met": met,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class ExperimentSuggestion:
    action: str
    risk: str                           # "low" | "medium" | "high"
    param_hint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "risk": self.risk, "param_hint": self.param_hint}


@dataclass
class Rule:
    id: str
    display_name: str
    description: str
    conditions: list[Condition]
    anti_conditions: list[Condition] = field(default_factory=list)
    min_score: float = 0.30
    experiments: list[ExperimentSuggestion] = field(default_factory=list)

    def score(self, fv: dict[str, Any]) -> tuple[float, list[dict], list[dict]]:
        """Return (score, evidence_list, anti_evidence_list)."""
        total_w = sum(c.weight for c in self.conditions) or 1.0
        hit_w = sum(c.weight for c in self.conditions if c.evaluate(fv))
        raw = hit_w / total_w

        penalty = 0.0
        for ac in self.anti_conditions:
            if ac.evaluate(fv):
                penalty += ac.weight

        final = max(0.0, raw - penalty)

        evidence = [c.to_dict(fv) for c in self.conditions if c.evaluate(fv)]
        anti_evidence = [ac.to_dict(fv) for ac in self.anti_conditions if ac.evaluate(fv)]
        return final, evidence, anti_evidence


# ── Rule catalogue ────────────────────────────────────────────────────────────

RULES: list[Rule] = [
    # ── R1: Routing detour due to congestion ──────────────────────────────────
    Rule(
        id="routing_detour",
        display_name="Routing detour (congestion-induced)",
        description=(
            "High congestion forces long detour routes, increasing net delays "
            "and causing setup violations on critical paths."
        ),
        conditions=[
            Condition("wns_ns", "<", -0.2, weight=0.35),
            Condition("congestion_hotspot_count", ">", 3, weight=0.30),
            Condition("utilization_pct", ">", 65.0, weight=0.20),
            Condition("tns_ns", "<", -1.0, weight=0.15),
        ],
        anti_conditions=[
            # If hold violations dominate, setup is probably not the main issue
            Condition("hold_violations", ">", 10, weight=0.15),
        ],
        min_score=0.30,
        experiments=[
            ExperimentSuggestion(
                action="Reduce CORE_UTILIZATION by 5% and rerun placement",
                risk="low",
                param_hint={"CORE_UTILIZATION": "-5%"},
            ),
            ExperimentSuggestion(
                action="Enable detailed routing DRC iterations (increase MAX_ROUTING_LAYER_ADJUSTMENT)",
                risk="low",
                param_hint={"MAX_ROUTING_LAYER_ADJUSTMENT": "1"},
            ),
            ExperimentSuggestion(
                action="Run congestion-aware global placement (increase PLACE_DENSITY)",
                risk="medium",
                param_hint={"PLACE_DENSITY": "+0.02"},
            ),
        ],
    ),

    # ── R2: CTS clock skew causing hold violations ────────────────────────────
    Rule(
        id="cts_skew",
        display_name="CTS clock skew (hold violation root cause)",
        description=(
            "Clock tree imbalance creates large skew between launch and capture "
            "flops, causing hold-time violations that cannot be fixed by routing."
        ),
        conditions=[
            Condition("hold_violations", ">", 0, weight=0.40),
            Condition("clock_skew_ns", ">", 0.08, weight=0.40),
            Condition("setup_violations", "<", 5, weight=0.20),
        ],
        anti_conditions=[
            Condition("wns_ns", "<", -0.5, weight=0.20),  # setup also bad → mixed issue
        ],
        min_score=0.30,
        experiments=[
            ExperimentSuggestion(
                action="Increase CTS_MAX_SLEW and CTS_MAX_CAP targets to allow more balanced buffers",
                risk="low",
                param_hint={"CTS_MAX_SLEW": "+10%"},
            ),
            ExperimentSuggestion(
                action="Run hold repair with stricter margin (TNS_END_PERCENT=0)",
                risk="low",
                param_hint={"TNS_END_PERCENT": "0"},
            ),
        ],
    ),

    # ── R3: Over-buffering side effect ────────────────────────────────────────
    Rule(
        id="over_buffering",
        display_name="Over-buffering (power / area blowup)",
        description=(
            "Aggressive buffer insertion to fix fanout/slew increases power "
            "consumption and may worsen congestion near high-fanout nodes."
        ),
        conditions=[
            Condition("max_fanout_violations", ">", 0, weight=0.35),
            Condition("total_power_mw", ">", 0.0, weight=0.20),   # any power data present
            Condition("max_slew_violations", ">", 0, weight=0.30),
            Condition("congestion_hotspot_count", ">", 2, weight=0.15),
        ],
        anti_conditions=[
            Condition("wns_ns", "<", -1.0, weight=0.15),  # severe setup → other issue likely
        ],
        min_score=0.25,
        experiments=[
            ExperimentSuggestion(
                action="Increase MAX_FANOUT target by 20% to reduce buffer insertion",
                risk="low",
                param_hint={"MAX_FANOUT": "+20%"},
            ),
            ExperimentSuggestion(
                action="Check high-fanout nets and manually size drivers",
                risk="medium",
                param_hint={},
            ),
        ],
    ),

    # ── R4: High density / placement saturation ───────────────────────────────
    Rule(
        id="density_saturation",
        display_name="Placement density saturation",
        description=(
            "Core utilization is too high, leaving insufficient whitespace for "
            "routing tracks and buffer insertion – causing both congestion and timing issues."
        ),
        conditions=[
            Condition("utilization_pct", ">", 75.0, weight=0.45),
            Condition("congestion_hotspot_count", ">", 5, weight=0.30),
            Condition("max_overflow", ">", 0.5, weight=0.25),
        ],
        anti_conditions=[],
        min_score=0.30,
        experiments=[
            ExperimentSuggestion(
                action="Reduce CORE_UTILIZATION to 70% or lower and rerun floorplan+place",
                risk="low",
                param_hint={"CORE_UTILIZATION": "70"},
            ),
            ExperimentSuggestion(
                action="Increase die area / IO ring padding",
                risk="medium",
                param_hint={"DIE_AREA": "expand"},
            ),
        ],
    ),

    # ── R5: Hold margin too tight (no skew issue, just margin) ────────────────
    Rule(
        id="hold_margin_tight",
        display_name="Hold margin insufficient (no significant skew)",
        description=(
            "Hold violations are present but clock skew is small.  "
            "The design has insufficient hold margin, likely from aggressive "
            "synthesis timing constraints or missing hold-fix iterations."
        ),
        conditions=[
            Condition("hold_violations", ">", 3, weight=0.50),
            Condition("clock_skew_ns", "<", 0.06, weight=0.30),
            Condition("wns_ns", ">", -0.1, weight=0.20),   # setup is fine
        ],
        anti_conditions=[
            Condition("clock_skew_ns", ">", 0.10, weight=0.25),  # if skew large → R2 is better
        ],
        min_score=0.30,
        experiments=[
            ExperimentSuggestion(
                action="Run dedicated hold-repair pass with HOLD_SLACK_MARGIN=0.05",
                risk="low",
                param_hint={"HOLD_SLACK_MARGIN": "0.05"},
            ),
            ExperimentSuggestion(
                action="Check that synthesis HOLD_MARGIN constraint is set correctly",
                risk="low",
                param_hint={},
            ),
        ],
    ),

    # ── R6: DRC concentrated with routing congestion ──────────────────────────
    Rule(
        id="drc_routing_congestion",
        display_name="DRC violations from routing congestion",
        description=(
            "DRC violations co-occur with congested routing regions, suggesting "
            "the router was forced into design-rule violations by lack of track space."
        ),
        conditions=[
            Condition("drc_total", ">", 5, weight=0.45),
            Condition("congestion_hotspot_count", ">", 3, weight=0.35),
            Condition("utilization_pct", ">", 60.0, weight=0.20),
        ],
        anti_conditions=[],
        min_score=0.30,
        experiments=[
            ExperimentSuggestion(
                action="Run detailed routing with stricter DRC iterations (GRT_OVERFLOW_ITERS=40)",
                risk="low",
                param_hint={"GRT_OVERFLOW_ITERS": "40"},
            ),
            ExperimentSuggestion(
                action="Reduce utilization to relieve routing congestion hotspots",
                risk="low",
                param_hint={"CORE_UTILIZATION": "-5%"},
            ),
            ExperimentSuggestion(
                action="Enable multi-cut via optimization to reduce DRC count",
                risk="medium",
                param_hint={"ENABLE_MULTI_CUT_VIA": "1"},
            ),
        ],
    ),
]

# Convenience lookup
RULE_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}
