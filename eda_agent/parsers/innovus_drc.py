"""Innovus DRC/geometry parser (separate from ORFS/OpenROAD parser).

Parses Innovus ``verifyGeometry`` summary output.  Typical summary section::

    ===================== Geometry Violation Summary ====================

    Layer Summary:
      metal1 : Short = 0, Spacing = 2, Width = 0, ...
    ...

    Total Violations by Type:
      Short            :   0
      Spacing          :   5
      Width            :   0
      Overlap          :   0
      SameNet          :   0
      Antenna          :   0
      ...
      Total            :   5

Also handles the older one-liner format::

    Cells   : 3
    SameNet : 0
    Wiring  : 2
    ...
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# Old one-liner category pattern
_CATEGORY_ROW = re.compile(
    r"^\s*(Cells|SameNet|Wiring|Antenna|Short|Overlap|Spacing|Width|OffGrid)\s*:\s*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# New "Total Violations by Type" table
_VIOLATION_ROW = re.compile(
    r"^\s*(Short|Spacing|Width|Overlap|SameNet|Antenna|OffGrid|MinArea|MinStep|ViaEnc)\s*:\s*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_TOTAL_LINE = re.compile(
    r"^\s*Total\s*:\s*(\d+)", re.MULTILINE | re.IGNORECASE
)
_NO_DRC = re.compile(r"No\s+DRC\s+violations\s+were\s+found", re.IGNORECASE)
_CLEAN  = re.compile(r"Total\s+Violations\s*[:\s]+0", re.IGNORECASE)


class InnovusDRCParser(BaseParser):
    """Parse Innovus verifyGeometry summary into drc summary record."""

    report_type = "innovus_drc"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        if _NO_DRC.search(text) or _CLEAN.search(text):
            return [{"kind": "summary", "total_violations": 0, "categories": {}}]

        # Try new table format first (longer categories list)
        new_rows = _VIOLATION_ROW.findall(text)
        total_m  = _TOTAL_LINE.search(text)

        if new_rows:
            categories = {name.lower(): int(cnt) for name, cnt in new_rows}
            total = int(total_m.group(1)) if total_m else sum(categories.values())
            return [
                {
                    "kind": "summary",
                    "total_violations": total,
                    "categories": categories,
                }
            ]

        # Fallback: old one-liner format
        old_rows = _CATEGORY_ROW.findall(text)
        if old_rows:
            categories = {name.lower(): int(cnt) for name, cnt in old_rows}
            total = sum(categories.values())
            return [
                {
                    "kind": "summary",
                    "total_violations": total,
                    "categories": categories,
                }
            ]

        raise ParseError("No Innovus DRC summary found in report text.")
