"""Innovus power report parser (separate from ORFS/OpenROAD parser)."""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

_TOTAL_INT = re.compile(r"Total\s+Internal\s+Power:\s*([\d.]+)", re.IGNORECASE)
_TOTAL_SW = re.compile(r"Total\s+Switching\s+Power:\s*([\d.]+)", re.IGNORECASE)
_TOTAL_LK = re.compile(r"Total\s+Leakage\s+Power:\s*([\d.]+)", re.IGNORECASE)
_TOTAL = re.compile(r"Total\s+Power:\s*([\d.]+)", re.IGNORECASE)
_UNIT_MW = re.compile(r"Power\s+Units\s*=\s*1mW", re.IGNORECASE)


class InnovusPowerParser(BaseParser):
    """Parse Innovus report_power output into summary record."""

    report_type = "innovus_power"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        int_m = _TOTAL_INT.search(text)
        sw_m = _TOTAL_SW.search(text)
        lk_m = _TOTAL_LK.search(text)
        tot_m = _TOTAL.search(text)

        if not any([int_m, sw_m, lk_m, tot_m]):
            raise ParseError("No Innovus power summary found in report text.")

        scale = 1e-3 if _UNIT_MW.search(text) else 1.0

        def f(m: re.Match[str] | None) -> float | None:
            return float(m.group(1)) * scale if m else None

        return [
            {
                "kind": "summary",
                "internal_power_w": f(int_m),
                "switching_power_w": f(sw_m),
                "leakage_power_w": f(lk_m),
                "total_power_w": f(tot_m),
            }
        ]
