"""Tests for the utilization report parser."""

from __future__ import annotations

import pytest

from eda_agent.parsers.utilization import UtilizationParser


def test_summary(utilization_report_text):
    parser = UtilizationParser()
    records = parser.parse_text(utilization_report_text)
    summaries = [r for r in records if r["kind"] == "summary"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["design_area_um2"] == pytest.approx(43210.0)
    assert s["utilization_pct"] == pytest.approx(42.0)
    assert s["num_cells"] == 247
    assert s["num_registers"] == 89


def test_cell_types(utilization_report_text):
    parser = UtilizationParser()
    records = parser.parse_text(utilization_report_text)
    cell_types = [r for r in records if r["kind"] == "cell_type"]
    names = {c["cell_type"] for c in cell_types}
    assert "$dff" in names
    dff = next(c for c in cell_types if c["cell_type"] == "$dff")
    assert dff["count"] == 89
