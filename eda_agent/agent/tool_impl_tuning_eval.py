"""Evaluation helpers for PPA target checks and bottleneck selection."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)


def check_ppa_target_impl(
    timing: dict[str, Any],
    target_spec: str,
    congestion_summary: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a natural-language PPA target against timing data."""
    summary = timing.get("summary", [])
    if not summary:
        return False

    latest = summary[0]
    spec_lower = target_spec.lower()

    metric_map = {
        "wns": "wns_ns",
        "tns": "tns_ns",
        "fmax": "fmax_mhz",
        "fep": "failing_endpoints",
        "failing_endpoints": "failing_endpoints",
        "failing endpoints": "failing_endpoints",
        "setup_violations": "setup_violations",
        "hold_violations": "hold_violations",
    }
    congestion_metric_map = {
        "overflow_h_pct": "overflow_h_pct",
        "overflow_v_pct": "overflow_v_pct",
    }

    timing_cond_re = re.compile(
        r"(wns|tns|fmax|fep|failing[_ ]endpoints|setup_violations|hold_violations)"
        r"\s*(>=|<=|>|<|==)\s*(-?[\d.]+)",
        re.IGNORECASE,
    )
    congestion_cond_re = re.compile(
        r"(overflow_h_pct|overflow_v_pct|overflow_pct|overflow)\s*(>=|<=|>|<|==)\s*(-?[\d.]+)%?",
        re.IGNORECASE,
    )

    timing_conditions = timing_cond_re.findall(spec_lower)
    congestion_conditions = congestion_cond_re.findall(spec_lower)
    if not timing_conditions and not congestion_conditions:
        return (latest.get("failing_endpoints") or 0) == 0

    def apply_op(op: str, actual: float, threshold: float) -> bool:
        if op == ">=":
            return actual >= threshold
        if op == "<=":
            return actual <= threshold
        if op == ">":
            return actual > threshold
        if op == "<":
            return actual < threshold
        if op == "==":
            return actual == threshold
        return False

    for metric_alias, op, raw_threshold in timing_conditions:
        data_key = metric_map.get(metric_alias.replace(" ", "_"))
        if data_key is None:
            continue
        actual = latest.get(data_key)
        if actual is None:
            return False
        if not apply_op(op, float(actual), float(raw_threshold)):
            return False

    if congestion_conditions:
        summary_data = congestion_summary or {}
        if not summary_data:
            return False
        for metric_alias, op, raw_threshold in congestion_conditions:
            alias = metric_alias.lower()
            if alias in {"overflow", "overflow_pct"}:
                overflow_h = float(summary_data.get("overflow_h_pct", 0.0) or 0.0)
                overflow_v = float(summary_data.get("overflow_v_pct", 0.0) or 0.0)
                actual = max(overflow_h, overflow_v)
            else:
                data_key = congestion_metric_map.get(alias)
                if data_key is None:
                    continue
                actual = summary_data.get(data_key)
            if actual is None:
                return False
            if not apply_op(op, float(actual), float(raw_threshold)):
                return False

    return True


def pick_bottleneck_stage_impl(
    timing: dict[str, Any],
    run_id: int | None = None,
    congestion_threshold_pct: float = 2.0,
    *,
    query_congestion_summary_fn: Callable[[int], dict[str, Any]],
) -> str:
    """Choose which stage to re-run based on violation profile."""
    summary = timing.get("summary", [{}])[0] if timing.get("summary") else {}
    if run_id is not None:
        try:
            congestion = query_congestion_summary_fn(run_id)
            overflow_h_pct = float(congestion.get("overflow_h_pct", 0.0) or 0.0)
            overflow_v_pct = float(congestion.get("overflow_v_pct", 0.0) or 0.0)
            if max(overflow_h_pct, overflow_v_pct) > congestion_threshold_pct:
                return "place"
        except Exception:
            logger.debug(
                "Failed to query congestion summary for run_id=%s",
                run_id,
                exc_info=True,
            )

    hold_vio = summary.get("hold_violations") or 0
    setup_vio = summary.get("setup_violations") or 0
    wns = summary.get("wns_ns") or 0.0
    fep = summary.get("failing_endpoints") or 0

    if hold_vio > 0:
        return "cts"
    if wns < -0.3 or setup_vio > 10 or fep > 20:
        return "cts"
    if fep > 0 or wns < 0:
        return "route"
    return "place"
