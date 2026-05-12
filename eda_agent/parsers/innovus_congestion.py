"""Innovus congestion report parser.

Parses the output of Innovus ``reportCongestion -overflow``.

Typical format::

    Usage: (6.5%H 5.9%V) = (1.838e+05um 2.357e+05um) = (36467 46762)
    Overflow: 13 = 13 (0.02% H) + 0 (0.00% V)

    Congestion distribution:

    Remain  cntH            cntV
    --------------------------------------
     -1:    13       0.02%  0        0.00%
    --------------------------------------
      0:    67       0.13%  3        0.01%
      1:    700      1.34%  147      0.27%
      ...
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# "Usage: (6.5%H 5.9%V) ..."
_USAGE = re.compile(
    r"Usage:\s+\(([\d.]+)%H\s+([\d.]+)%V\)",
    re.IGNORECASE,
)

# "Overflow: 13 = 13 (0.02% H) + 0 (0.00% V)"
_OVERFLOW_TOTAL = re.compile(
    r"Overflow:\s+(\d+)\s*=\s*(\d+)\s*\(([\d.]+)%\s*H\)\s*\+\s*(\d+)\s*\(([\d.]+)%\s*V\)",
    re.IGNORECASE,
)

# Overflow-only row (remain = -1):  " -1:    13  0.02%  0  0.00%"
_OVERFLOW_ROW = re.compile(
    r"^\s*-1:\s+(\d+)\s+([\d.]+)%\s+(\d+)\s+([\d.]+)%",
    re.MULTILINE,
)


class InnovusCongestionParser(BaseParser):
    """Parse Innovus reportCongestion -overflow output."""

    report_type = "innovus_congestion"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        usage_m    = _USAGE.search(text)
        overflow_m = _OVERFLOW_TOTAL.search(text)
        row_m      = _OVERFLOW_ROW.search(text)

        if not (usage_m or overflow_m or row_m):
            raise ParseError("No Innovus congestion data found in report text.")

        result: dict[str, Any] = {"kind": "summary"}

        if usage_m:
            result["usage_h_pct"] = float(usage_m.group(1))
            result["usage_v_pct"] = float(usage_m.group(2))

        if overflow_m:
            result["total_overflow"]    = int(overflow_m.group(1))
            result["overflow_h"]        = int(overflow_m.group(2))
            result["overflow_h_pct"]    = float(overflow_m.group(3))
            result["overflow_v"]        = int(overflow_m.group(4))
            result["overflow_v_pct"]    = float(overflow_m.group(5))
        elif row_m:
            # Fallback: parse the -1 row directly
            h_cnt = int(row_m.group(1))
            v_cnt = int(row_m.group(3))
            result["total_overflow"] = h_cnt + v_cnt
            result["overflow_h"]     = h_cnt
            result["overflow_h_pct"] = float(row_m.group(2))
            result["overflow_v"]     = v_cnt
            result["overflow_v_pct"] = float(row_m.group(4))
        else:
            result["total_overflow"] = 0
            result["overflow_h"]     = 0
            result["overflow_v"]     = 0

        return [result]
