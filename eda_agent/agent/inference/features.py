"""Feature extraction for the Root Cause Inference Engine.

Queries the four analytics tables (timing_summary, congestion_hotspots,
utilization_summary, power_summary, drc_violations) for a given *run_id*
and returns a flat ``FeatureVector`` dict that the rule engine can consume
directly.

All values are numeric (``float | int``) or ``None`` when the data is absent.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from sqlalchemy import text

from eda_agent.db.session import get_db

logger = logging.getLogger(__name__)


class FeatureVector(TypedDict, total=False):
    # ── timing ────────────────────────────────────────────────────────────────
    wns_ns: float | None                 # worst negative slack (setup)
    tns_ns: float | None                 # total negative slack
    failing_endpoints: int | None        # number of failing setup endpoints
    hold_violations: int | None          # hold violation count
    setup_violations: int | None         # setup violation count
    clock_skew_ns: float | None          # max clock skew
    max_fanout_violations: int | None
    max_slew_violations: int | None
    max_cap_violations: int | None
    critical_path_delay_ns: float | None
    fmax_mhz: float | None

    # ── congestion ────────────────────────────────────────────────────────────
    congestion_hotspot_count: int | None # number of congestion hotspot records
    max_overflow: float | None           # worst single-hotspot overflow value

    # ── utilization ───────────────────────────────────────────────────────────
    utilization_pct: float | None
    num_cells: int | None

    # ── power ─────────────────────────────────────────────────────────────────
    total_power_mw: float | None
    dynamic_power_mw: float | None
    leakage_power_mw: float | None

    # ── DRC ───────────────────────────────────────────────────────────────────
    drc_total: int | None                # total DRC violation count (SUMMARY row)


def extract_features(run_id: int) -> FeatureVector:
    """Return a FeatureVector for *run_id*.

    Missing / NULL values are left as ``None``.  If *run_id* does not exist the
    function still returns a valid (mostly-None) dict rather than raising.
    """
    fv: FeatureVector = {
        "wns_ns": None,
        "tns_ns": None,
        "failing_endpoints": None,
        "hold_violations": None,
        "setup_violations": None,
        "clock_skew_ns": None,
        "max_fanout_violations": None,
        "max_slew_violations": None,
        "max_cap_violations": None,
        "critical_path_delay_ns": None,
        "fmax_mhz": None,
        "congestion_hotspot_count": None,
        "max_overflow": None,
        "utilization_pct": None,
        "num_cells": None,
        "total_power_mw": None,
        "dynamic_power_mw": None,
        "leakage_power_mw": None,
        "drc_total": None,
    }

    try:
        with get_db() as db:
            # ── timing_summary (take worst-slack row for this run) ────────────
            ts = db.execute(
                text(
                    """
                    SELECT wns_ns, tns_ns, failing_endpoints,
                           hold_violations, setup_violations,
                           clock_skew_ns, max_fanout_violations,
                           max_slew_violations, max_cap_violations,
                           critical_path_delay_ns, fmax_mhz
                    FROM timing_summary
                    WHERE run_id = :run_id
                    ORDER BY wns_ns ASC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"run_id": run_id},
            ).mappings().first()
            if ts:
                fv["wns_ns"] = ts["wns_ns"]
                fv["tns_ns"] = ts["tns_ns"]
                fv["failing_endpoints"] = ts["failing_endpoints"]
                fv["hold_violations"] = ts["hold_violations"]
                fv["setup_violations"] = ts["setup_violations"]
                fv["clock_skew_ns"] = ts["clock_skew_ns"]
                fv["max_fanout_violations"] = ts["max_fanout_violations"]
                fv["max_slew_violations"] = ts["max_slew_violations"]
                fv["max_cap_violations"] = ts["max_cap_violations"]
                fv["critical_path_delay_ns"] = ts["critical_path_delay_ns"]
                fv["fmax_mhz"] = ts["fmax_mhz"]

            # ── congestion_hotspots ───────────────────────────────────────────
            cong = db.execute(
                text(
                    """
                    SELECT COUNT(*) AS cnt,
                           MAX(overflow) AS max_overflow
                    FROM congestion_hotspots
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            ).mappings().first()
            if cong:
                fv["congestion_hotspot_count"] = int(cong["cnt"] or 0)
                fv["max_overflow"] = cong["max_overflow"]

            # ── utilization_summary ───────────────────────────────────────────
            util = db.execute(
                text(
                    """
                    SELECT utilization_pct, num_cells
                    FROM utilization_summary
                    WHERE run_id = :run_id
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"run_id": run_id},
            ).mappings().first()
            if util:
                fv["utilization_pct"] = util["utilization_pct"]
                fv["num_cells"] = util["num_cells"]

            # ── power_summary ─────────────────────────────────────────────────
            pwr = db.execute(
                text(
                    """
                    SELECT total_power_mw, dynamic_power_mw, leakage_power_mw
                    FROM power_summary
                    WHERE run_id = :run_id
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"run_id": run_id},
            ).mappings().first()
            if pwr:
                fv["total_power_mw"] = pwr["total_power_mw"]
                fv["dynamic_power_mw"] = pwr["dynamic_power_mw"]
                fv["leakage_power_mw"] = pwr["leakage_power_mw"]

            # ── drc_violations (SUMMARY row) ──────────────────────────────────
            drc = db.execute(
                text(
                    """
                    SELECT SUM(total_violations) AS total
                    FROM drc_violations
                    WHERE run_id = :run_id
                      AND violation_type = 'SUMMARY'
                    """
                ),
                {"run_id": run_id},
            ).mappings().first()
            if drc and drc["total"] is not None:
                fv["drc_total"] = int(drc["total"])

    except Exception:
        logger.warning(
            "Feature extraction failed for run_id=%s – returning partial vector",
            run_id,
            exc_info=True,
        )

    return fv
