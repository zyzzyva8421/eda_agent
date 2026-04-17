"""Tests for the timing report parser."""

from __future__ import annotations

import pytest

from eda_agent.parsers.timing import TimingParser


def test_summary_extracted(timing_report_text):
    parser = TimingParser()
    records = parser.parse_text(timing_report_text)
    summaries = [r for r in records if r["kind"] == "summary"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["wns_ns"] == pytest.approx(-0.342)
    assert s["tns_ns"] == pytest.approx(-12.451)
    assert s["failing_endpoints"] == 7
    assert s["view"] == "setup_typical"


def test_paths_extracted(timing_report_text):
    parser = TimingParser()
    records = parser.parse_text(timing_report_text)
    paths = [r for r in records if r["kind"] == "path"]
    assert len(paths) == 2
    slacks = sorted(p["slack_ns"] for p in paths)
    assert slacks[0] == pytest.approx(-0.342)
    assert slacks[1] == pytest.approx(-0.128)


def test_path_fields(timing_report_text):
    parser = TimingParser()
    records = parser.parse_text(timing_report_text)
    paths = [r for r in records if r["kind"] == "path"]
    p = paths[0]
    assert "startpoint" in p
    assert "endpoint" in p
    assert p["path_group"] == "clk"


def test_empty_raises():
    from eda_agent.parsers.base import ParseError

    parser = TimingParser()
    with pytest.raises(ParseError):
        parser.parse_text("no timing data here")
