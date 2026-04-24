"""Tests for the DRCParser."""

from __future__ import annotations

import pytest

from eda_agent.parsers.drc import DRCParser


@pytest.fixture
def parser() -> DRCParser:
    return DRCParser()


_SUMMARY_ONLY = "[INFO DRC-0007] 0 violations found.\n"

_VIOLATIONS_REPORT = """\
[INFO DRC-0007] 3 violations found.

violation type: Short
      srcs: net:_0123_ net:_0456_
      bbox = (100.00, 200.00) - (110.00, 210.00) on Layer metal1

violation type: Metal spacing
      srcs: net:clk
      bbox = (50.50, 75.25) - (55.50, 80.25) on Layer metal2

violation type: Width
      bbox = (0.00, 0.00) - (1.00, 1.00) on Layer metal3
"""


def test_parse_summary_zero_violations(parser):
    records = parser.parse_text(_SUMMARY_ONLY)
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["total_violations"] == 0


def test_parse_summary_count(parser):
    records = parser.parse_text(_VIOLATIONS_REPORT)
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["total_violations"] == 3


def test_parse_violations_details(parser):
    records = parser.parse_text(_VIOLATIONS_REPORT)
    violations = [r for r in records if r["kind"] == "drc_violation"]
    assert len(violations) == 3

    short = next(r for r in violations if r["violation_type"] == "Short")
    assert short["layer"] == "metal1"
    assert "net:_0123_" in short["nets"]
    assert short["bbox_wkt"] is not None
    assert "100.0" in short["bbox_wkt"]


def test_parse_violation_no_bbox(parser):
    report = "1 violations found.\nviolation type: Short\n      srcs: net:foo\n"
    records = parser.parse_text(report)
    v = next(r for r in records if r["kind"] == "drc_violation")
    assert v["bbox_wkt"] is None


def test_no_drc_data_raises(parser):
    from eda_agent.parsers.base import ParseError

    with pytest.raises(ParseError):
        parser.parse_text("nothing useful here")


def test_report_type():
    assert DRCParser.report_type == "drc"
