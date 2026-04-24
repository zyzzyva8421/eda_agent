"""Tests for the PowerParser."""

from __future__ import annotations

import pytest

from eda_agent.parsers.power import PowerParser


@pytest.fixture
def parser() -> PowerParser:
    return PowerParser()


_WATT_REPORT = """\
================================= Power ==================================
Group                  Internal  Switching   Leakage     Total
                          (W)        (W)        (W)        (W)
-------------------------------------------------------------------------
Sequential             1.78e-04   3.43e-05   0.00e+00   2.12e-04
Combinational          3.15e-04   1.27e-04   0.00e+00   4.42e-04
-------------------------------------------------------------------------
Total                  4.93e-04   1.61e-04   0.00e+00   6.54e-04
Percentage               75.4%      24.6%       0.0%     100.0%
"""

_MW_REPORT = """\
Group                  Internal  Switching   Leakage     Total
                          (mW)       (mW)       (mW)      (mW)
Sequential             0.17844    0.034267    0.00000    0.21271
Combinational          0.31479    0.12689     0.00000    0.44168
Total                  0.49323    0.16116     0.00000    0.65439
"""


def test_parse_watt_summary(parser):
    records = parser.parse_text(_WATT_REPORT)
    summary = next(r for r in records if r["kind"] == "summary")
    assert abs(summary["total_power_w"] - 6.54e-04) < 1e-8
    assert abs(summary["internal_power_w"] - 4.93e-04) < 1e-8
    assert abs(summary["switching_power_w"] - 1.61e-04) < 1e-8
    assert summary["leakage_power_w"] == 0.0


def test_parse_mw_converted_to_watts(parser):
    records = parser.parse_text(_MW_REPORT)
    summary = next(r for r in records if r["kind"] == "summary")
    # 0.65439 mW → 6.5439e-4 W
    assert abs(summary["total_power_w"] - 0.65439e-3) < 1e-9


def test_parse_power_groups(parser):
    records = parser.parse_text(_WATT_REPORT)
    groups = [r for r in records if r["kind"] == "power_group"]
    group_names = {r["group_name"] for r in groups}
    assert "sequential" in group_names
    assert "combinational" in group_names


def test_no_power_data_raises(parser):
    from eda_agent.parsers.base import ParseError

    with pytest.raises(ParseError):
        parser.parse_text("nothing useful here")


def test_report_type():
    assert PowerParser.report_type == "power"
