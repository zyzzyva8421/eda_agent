"""Tests for the congestion report parser."""

from __future__ import annotations

import pytest

from eda_agent.parsers.congestion import CongestionParser


def test_summary(congestion_report_text):
    parser = CongestionParser()
    records = parser.parse_text(congestion_report_text)
    summaries = [r for r in records if r["kind"] == "summary"]
    assert len(summaries) == 1
    s = summaries[0]
    assert s["total_overflow"] == 4


def test_hotspots(congestion_report_text):
    parser = CongestionParser()
    records = parser.parse_text(congestion_report_text)
    hotspots = [r for r in records if r["kind"] == "hotspot"]
    assert len(hotspots) == 2
    overflows = sorted(h["overflow"] for h in hotspots)
    assert overflows == [1, 2]


def test_hotspot_wkt(congestion_report_text):
    parser = CongestionParser()
    records = parser.parse_text(congestion_report_text)
    hotspot = next(r for r in records if r["kind"] == "hotspot" and r["overflow"] == 2)
    assert hotspot["x1"] == 42
    assert hotspot["y1"] == 17
    assert hotspot["x2"] == 43
    assert hotspot["y2"] == 18
    assert "POLYGON" in hotspot["wkt"]


def test_layer_rows(congestion_report_text):
    parser = CongestionParser()
    records = parser.parse_text(congestion_report_text)
    layers = [r for r in records if r["kind"] == "layer"]
    assert len(layers) == 3
    metal2 = next(l for l in layers if l["layer"].lower() == "metal2")
    assert metal2["direction"] == "V"
    assert metal2["overflow"] == 3
