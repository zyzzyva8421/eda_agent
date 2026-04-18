"""Tests for the parser registry."""

from __future__ import annotations

import pytest

from eda_agent.parsers import get_parser, register_parser
from eda_agent.parsers.base import BaseParser, ParseError


def test_get_known_parsers():
    for name in ("timing", "congestion", "utilization"):
        p = get_parser(name)
        assert p.report_type == name


def test_get_unknown_parser():
    with pytest.raises(KeyError):
        get_parser("power_nonexistent")


def test_register_custom_parser():
    class PowerParser(BaseParser):
        report_type = "power"

        def parse_text(self, text):
            return [{"kind": "summary", "total_power_uw": 1.23}]

    register_parser(PowerParser())
    p = get_parser("power")
    records = p.parse_text("dummy")
    assert records[0]["total_power_uw"] == 1.23
