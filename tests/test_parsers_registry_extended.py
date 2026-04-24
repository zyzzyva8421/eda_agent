"""Tests for the parser registry with power and DRC parsers."""

from __future__ import annotations

from eda_agent.parsers import get_parser


def test_get_all_builtin_parsers():
    for name in ("timing", "congestion", "utilization", "power", "drc"):
        p = get_parser(name)
        assert p.report_type == name


def test_power_parser_registered():
    p = get_parser("power")
    assert p.report_type == "power"


def test_drc_parser_registered():
    p = get_parser("drc")
    assert p.report_type == "drc"
