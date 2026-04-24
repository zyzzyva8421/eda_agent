"""Power report parser.

Parses the per-group power report produced by OpenROAD (``report_power``).

Typical output::

    ================================= Power ==================================
    Group                  Internal  Switching   Leakage     Total
                              (W)        (W)        (W)        (W)
    -------------------------------------------------------------------------
    Sequential             1.78e-04   3.43e-05   0.00e+00   2.12e-04
    Combinational          3.15e-04   1.27e-04   0.00e+00   4.42e-04
    -------------------------------------------------------------------------
    Total                  4.93e-04   1.61e-04   0.00e+00   6.54e-04
    Percentage               75.4%      24.6%       0.0%     100.0%

mW-unit variant (some ORFS versions)::

    Group                  Internal  Switching   Leakage     Total
                              (mW)       (mW)       (mW)      (mW)
    Sequential             0.17844    0.034267    0.00000    0.21271
    Combinational          0.31479    0.12689     0.00000    0.44168
    Total                  0.49323    0.16116     0.00000    0.65439
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# ── Power table row ───────────────────────────────────────────────────────────

# Matches group rows and the Total row:
#   Sequential   1.78e-04  3.43e-05  0.00e+00  2.12e-04
#   Total        4.93e-04  1.61e-04  0.00e+00  6.54e-04
_POWER_ROW = re.compile(
    r"^(Sequential|Combinational|Macro|Pad|Clock|Total)\s+"
    r"([\d.e+\-]+)\s+([\d.e+\-]+)\s+([\d.e+\-]+)\s+([\d.e+\-]+)",
    re.MULTILINE | re.IGNORECASE,
)

# Detect unit: "(mW)" → multiply by 1e-3 to convert to Watts
_UNIT_MW = re.compile(r"\(\s*mW\s*\)", re.IGNORECASE)


class PowerParser(BaseParser):
    """Parse OpenROAD power reports into summary and per-group records."""

    report_type = "power"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        """Return a list with a ``{"kind": "summary", ...}`` record and optional
        ``{"kind": "power_group", ...}`` records for each named group.
        """
        records: list[dict[str, Any]] = []

        scale = 1e-3 if _UNIT_MW.search(text) else 1.0

        summary = self._parse_summary(text, scale)
        if summary:
            records.append(summary)

        records.extend(self._parse_groups(text, scale))

        if not records:
            raise ParseError("No power data found in report text.")
        return records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_summary(self, text: str, scale: float) -> dict[str, Any] | None:
        for m in _POWER_ROW.finditer(text):
            if m.group(1).lower() == "total":
                return {
                    "kind": "summary",
                    "internal_power_w": float(m.group(2)) * scale,
                    "switching_power_w": float(m.group(3)) * scale,
                    "leakage_power_w": float(m.group(4)) * scale,
                    "total_power_w": float(m.group(5)) * scale,
                }
        return None

    def _parse_groups(self, text: str, scale: float) -> list[dict[str, Any]]:
        groups = []
        for m in _POWER_ROW.finditer(text):
            group_name = m.group(1).lower()
            if group_name == "total":
                continue
            groups.append(
                {
                    "kind": "power_group",
                    "group_name": group_name,
                    "internal_power_w": float(m.group(2)) * scale,
                    "switching_power_w": float(m.group(3)) * scale,
                    "leakage_power_w": float(m.group(4)) * scale,
                    "total_power_w": float(m.group(5)) * scale,
                }
            )
        return groups
