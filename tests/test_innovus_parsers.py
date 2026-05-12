"""Tests for Innovus parsers using real report fixtures from the VM."""

from __future__ import annotations

from pathlib import Path

import pytest

from eda_agent.parsers import get_parser

FIXTURES = Path(__file__).parent / "fixtures" / "innovus"


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

class TestInnovusTimingParser:
    def _parse(self, filename: str):
        p = get_parser("innovus_timing")
        return p.parse_file(FIXTURES / filename)

    def test_place_timing_summary(self):
        records = self._parse("place_timing.rpt")
        summary = next(r for r in records if r["kind"] == "summary")
        # At least one path parsed
        assert summary["total_paths"] >= 1
        # wns should be a float
        assert isinstance(summary["wns_ns"], float)
        # tns should be 0.0 or negative
        assert summary["tns_ns"] <= 0.0 or summary["tns_ns"] == 0.0
        # failing_endpoints is int
        assert isinstance(summary["failing_endpoints"], int)

    def test_place_timing_paths(self):
        records = self._parse("place_timing.rpt")
        paths = [r for r in records if r["kind"] == "path"]
        assert len(paths) >= 1
        for path in paths:
            assert "slack_ns" in path
            assert isinstance(path["slack_ns"], float)
            assert "violated" in path

    def test_route_timing_has_hold_path(self):
        """Route timing report has hold check paths."""
        records = self._parse("route_timing.rpt")
        summary = next(r for r in records if r["kind"] == "summary")
        assert summary["total_paths"] >= 1

    def test_wns_is_minimum_slack(self):
        """WNS must equal minimum of all per-path slacks."""
        records = self._parse("place_timing.rpt")
        summary = next(r for r in records if r["kind"] == "summary")
        paths = [r for r in records if r["kind"] == "path"]
        if paths:
            min_slack = min(p["slack_ns"] for p in paths)
            assert abs(summary["wns_ns"] - min_slack) < 1e-9


# ---------------------------------------------------------------------------
# Utilization / Area
# ---------------------------------------------------------------------------

class TestInnovusUtilizationParser:
    def _parse(self, filename: str):
        p = get_parser("innovus_utilization")
        return p.parse_file(FIXTURES / filename)

    def test_parse_area(self):
        records = self._parse("place_area.rpt")
        assert len(records) == 1
        r = records[0]
        assert r["kind"] == "summary"
        # DTMF_CHIP has 5667 instances
        assert r["num_cells"] == 5667
        # Area ~ 1274168 um^2
        assert abs(r["design_area_um2"] - 1274168.74283) < 1.0

    def test_num_cells_positive(self):
        records = self._parse("place_area.rpt")
        assert records[0]["num_cells"] > 0

    def test_design_area_positive(self):
        records = self._parse("place_area.rpt")
        assert records[0]["design_area_um2"] > 0


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------

class TestInnovusPowerParser:
    def _parse(self, filename: str):
        p = get_parser("innovus_power")
        return p.parse_file(FIXTURES / filename)

    def test_parse_total_power(self):
        records = self._parse("place_power.rpt")
        assert len(records) == 1
        r = records[0]
        assert r["kind"] == "summary"
        # Power Units = 1mW → values multiplied by 1e-3 → ~0.082 W
        assert r["total_power_w"] is not None
        assert 0.05 < r["total_power_w"] < 0.2, f"Unexpected total_power_w={r['total_power_w']}"

    def test_parse_power_breakdown(self):
        records = self._parse("place_power.rpt")
        r = records[0]
        assert r["internal_power_w"] is not None
        assert r["switching_power_w"] is not None
        assert r["leakage_power_w"] is not None
        # internal >> switching >> leakage
        assert r["internal_power_w"] > r["switching_power_w"] > r["leakage_power_w"]

    def test_power_sum_consistent(self):
        records = self._parse("place_power.rpt")
        r = records[0]
        reconstructed = r["internal_power_w"] + r["switching_power_w"] + r["leakage_power_w"]
        assert abs(reconstructed - r["total_power_w"]) < 1e-4


# ---------------------------------------------------------------------------
# DRC
# ---------------------------------------------------------------------------

class TestInnovusDRCParser:
    def _parse(self, filename: str):
        p = get_parser("innovus_drc")
        return p.parse_file(FIXTURES / filename)

    def test_parse_drc_clean(self):
        """Post-route DRC should be clean for this design."""
        records = self._parse("route_drc.rpt")
        assert len(records) == 1
        r = records[0]
        assert r["kind"] == "summary"
        assert r["total_violations"] == 0

    def test_drc_has_categories(self):
        records = self._parse("route_drc.rpt")
        r = records[0]
        assert "categories" in r
        assert isinstance(r["categories"], dict)

    def test_drc_categories_consistent(self):
        """Sum of category values == total_violations."""
        records = self._parse("route_drc.rpt")
        r = records[0]
        total_from_cats = sum(r["categories"].values())
        assert total_from_cats == r["total_violations"]


# ---------------------------------------------------------------------------
# Congestion
# ---------------------------------------------------------------------------

class TestInnovusCongestionParser:
    def _parse(self, filename: str):
        p = get_parser("innovus_congestion")
        return p.parse_file(FIXTURES / filename)

    def test_parse_congestion(self):
        records = self._parse("route_congestion.rpt")
        assert len(records) == 1
        r = records[0]
        assert r["kind"] == "summary"
        assert "total_overflow" in r

    def test_overflow_value(self):
        records = self._parse("route_congestion.rpt")
        r = records[0]
        # From real report: Overflow: 13 = 13 (H) + 0 (V)
        assert r["total_overflow"] == 13
        assert r["overflow_h"] == 13
        assert r["overflow_v"] == 0

    def test_usage_pct(self):
        records = self._parse("route_congestion.rpt")
        r = records[0]
        assert "usage_h_pct" in r
        assert "usage_v_pct" in r
        # From real report: 6.5%H 5.9%V
        assert abs(r["usage_h_pct"] - 6.5) < 0.1
        assert abs(r["usage_v_pct"] - 5.9) < 0.1
