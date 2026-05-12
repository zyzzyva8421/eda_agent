"""Innovus DRC/geometry parser (separate from ORFS/OpenROAD parser)."""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

_SUMMARY_ROW = re.compile(
    r"^\s*(Cells|SameNet|Wiring|Antenna|Short|Overlap)\s*:\s*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_NO_DRC = re.compile(r"No\s+DRC\s+violations\s+were\s+found", re.IGNORECASE)


class InnovusDRCParser(BaseParser):
    """Parse Innovus verifyGeometry summary into drc summary record."""

    report_type = "innovus_drc"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        rows = _SUMMARY_ROW.findall(text)
        if rows:
            total = sum(int(v) for _name, v in rows)
            return [{"kind": "summary", "total_violations": total}]

        if _NO_DRC.search(text):
            return [{"kind": "summary", "total_violations": 0}]

        raise ParseError("No Innovus DRC summary found in report text.")
