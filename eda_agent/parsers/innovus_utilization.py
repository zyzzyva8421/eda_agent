"""Innovus utilization/area parser (separate from ORFS/OpenROAD parser).

Parses Innovus ``report_area`` output.  The top-level row has depth 0::

    Depth  Name       #Inst  Area (um^2)
    0      DTMF_CHIP  5667   1274168.74283

Utilization % requires core area.  Innovus logs the core area in the
floorplan / saveDesign summary lines such as::

    Core Area: 1850400.00000 um^2
    Cell Area: 1274168.74283 um^2
    Core Utilization: 68.858 %

Those lines may or may not be present in area.rpt.  When missing,
utilization_pct is returned as None.
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# Top-level row: depth=0
_TOP_ROW = re.compile(r"^0\s+\S+\s+(\d+)\s+([\d.]+)\s*$", re.MULTILINE)

# Core / cell area summary lines (may appear in combined report output)
_CORE_AREA  = re.compile(r"Core\s+Area\s*[:\s]+([\d.]+)", re.IGNORECASE)
_CELL_AREA  = re.compile(r"Cell\s+Area\s*[:\s]+([\d.]+)", re.IGNORECASE)
_CORE_UTIL  = re.compile(r"Core\s+Utilization\s*[:\s]+([\d.]+)\s*%?", re.IGNORECASE)

# Innovus sometimes prints: "Total area of standard cells:  1274168.74"
_STD_AREA   = re.compile(r"Total\s+area\s+of\s+standard\s+cells\s*[:\s]+([\d.]+)", re.IGNORECASE)


class InnovusUtilizationParser(BaseParser):
    """Parse Innovus area report into utilization summary record."""

    report_type = "innovus_utilization"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        m = _TOP_ROW.search(text)
        if not m:
            raise ParseError("No Innovus area summary found in report text.")

        num_cells = int(m.group(1))
        area_um2  = float(m.group(2))

        # Try to derive utilization %
        util_pct: float | None = None
        core_m = _CORE_AREA.search(text)
        util_m = _CORE_UTIL.search(text)

        if util_m:
            util_pct = float(util_m.group(1))
        elif core_m:
            core_area = float(core_m.group(1))
            if core_area > 0:
                util_pct = round(area_um2 / core_area * 100, 3)

        return [
            {
                "kind": "summary",
                "design_area_um2": area_um2,
                "utilization_pct": util_pct,
                "num_cells": num_cells,
                "num_registers": None,
            }
        ]
