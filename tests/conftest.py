"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def timing_report_text() -> str:
    sep = "-" * 90
    return f"""\
wns -0.342
tns -12.451
violating paths 7
view setup_typical

{sep}
Startpoint: u_core/u_rx/data_reg[0]
             (rising edge-triggered flip-flop clocked by clk)
Endpoint:   u_core/u_tx/out_reg[3]
             (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
slack (VIOLATED) -0.342
{sep}
Startpoint: u_core/u_mac/a_reg[1]
Endpoint:   u_core/u_mac/b_reg[1]
Path Group: clk
slack (VIOLATED) -0.128
{sep}
"""


@pytest.fixture
def timing_report_extended_text() -> str:
    """Timing report that also contains ORFS extended metrics."""
    sep = "-" * 90
    return f"""\
wns -0.342
tns -12.451
violating paths 7
view setup_typical
clk period_min = 4.19 fmax = 238.86
setup skew 0.12
max slew violation count 3
max fanout violation count 1
max cap violation count 0
setup violation count 7
hold violation count 2
critical path delay
  4.19
slack div critical path delay
  0.918

{sep}
Startpoint: u_core/u_rx/data_reg[0]
Endpoint:   u_core/u_tx/out_reg[3]
Path Group: clk
slack (VIOLATED) -0.342
{sep}
"""


@pytest.fixture
def congestion_report_text() -> str:
    return """\
Global Routing Congestion Report
---------------------------------
Layer  Direction  Overflow  Max H/V Usage  Available  Resources
metal1  H         0         0.72          120        141
metal2  V         3         0.91           98        107
metal3  H         1         0.85          110        130
Total overflow: 4
Worst congestion tile: (42, 17) to (43, 18) overflow=2
Worst congestion tile: (10, 5) to (11, 6) overflow=1
"""


@pytest.fixture
def utilization_report_text() -> str:
    return """\
Design area 43210 u^2 42% utilization.
Number of cells: 247
Number of registers: 89

   $dff  89
   $add  34
   $_NOT_  12
"""
