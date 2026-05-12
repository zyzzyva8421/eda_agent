"""Innovus utilization/area parser (separate from ORFS/OpenROAD parser)."""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# Innovus hierarchy area table top row:
# 0      DTMF_CHIP   5667   1274168.74283
_TOP_ROW = re.compile(r"^0\s+\S+\s+(\d+)\s+([\d.]+)\s*$", re.MULTILINE)


class InnovusUtilizationParser(BaseParser):
    """Parse Innovus area report into utilization summary record."""

    report_type = "innovus_utilization"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        m = _TOP_ROW.search(text)
        if not m:
            raise ParseError("No Innovus area summary found in report text.")

        num_cells = int(m.group(1))
        area_um2 = float(m.group(2))

        return [
            {
                "kind": "summary",
                "design_area_um2": area_um2,
                "utilization_pct": None,
                "num_cells": num_cells,
                "num_registers": None,
            }
        ]
