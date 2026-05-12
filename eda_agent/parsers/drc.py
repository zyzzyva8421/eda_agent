"""DRC (Design Rule Check) report parser.

Handles the violation report format produced by OpenROAD / ORFS.

Summary line::

    [INFO DRC-0007] 5 violations found.

Detailed violation block::

    violation type: Short
          srcs: net:_0123_ net:_0456_
          bbox = (100.00, 200.00) - (110.00, 210.00) on Layer metal1

Multiple violations may appear sequentially in the same file.
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# ── Patterns ──────────────────────────────────────────────────────────────────

# Summary count line:  "0 violations found" or "[INFO DRC-0007] 5 violations found."
_DRC_SUMMARY = re.compile(r"(\d+)\s+violation[s]?\s+found", re.IGNORECASE)

# Violation type header line
_VIOLATION_TYPE = re.compile(
    r"^violation\s+type\s*:\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)

# Net sources
_VIOLATION_SRCS = re.compile(
    r"srcs\s*:\s*(.+?)(?=\nbbox|\ncomment|\nviolation|$)",
    re.IGNORECASE | re.DOTALL,
)

# Bounding box
_VIOLATION_BBOX = re.compile(
    r"bbox\s*=\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*-\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
    re.IGNORECASE,
)

# Layer name following the bbox
_VIOLATION_LAYER = re.compile(r"on\s+Layer\s+(\S+)", re.IGNORECASE)
_INNOVUS_SUMMARY_ROW = re.compile(r"^\s*(Cells|SameNet|Wiring|Antenna|Short|Overlap)\s*:\s*(\d+)", re.MULTILINE | re.IGNORECASE)
_INNOVUS_NO_DRC = re.compile(r"No\s+DRC\s+violations\s+were\s+found", re.IGNORECASE)


class DRCParser(BaseParser):
    """Parse OpenROAD / ORFS DRC reports."""

    report_type = "drc"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        summary = self._parse_summary(text)
        if summary:
            records.append(summary)

        records.extend(self._parse_violations(text))

        if not records:
            raise ParseError("No DRC data found in report text.")
        return records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_summary(self, text: str) -> dict[str, Any] | None:
        m = _DRC_SUMMARY.search(text)
        if m:
            return {"kind": "summary", "total_violations": int(m.group(1))}
        innovus_rows = _INNOVUS_SUMMARY_ROW.findall(text)
        if innovus_rows:
            total = sum(int(count) for _name, count in innovus_rows)
            return {"kind": "summary", "total_violations": total}
        if _INNOVUS_NO_DRC.search(text):
            return {"kind": "summary", "total_violations": 0}
        return None

    def _parse_violations(self, text: str) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        # Split on each "violation type:" header to get per-violation blocks
        blocks = re.split(r"(?=violation\s+type\s*:)", text, flags=re.IGNORECASE)
        for block in blocks:
            type_m = _VIOLATION_TYPE.search(block)
            if not type_m:
                continue

            bbox_m = _VIOLATION_BBOX.search(block)
            layer_m = _VIOLATION_LAYER.search(block)
            srcs_m = _VIOLATION_SRCS.search(block)

            x1 = float(bbox_m.group(1)) if bbox_m else None
            y1 = float(bbox_m.group(2)) if bbox_m else None
            x2 = float(bbox_m.group(3)) if bbox_m else None
            y2 = float(bbox_m.group(4)) if bbox_m else None

            nets: list[str] = []
            if srcs_m:
                nets = [n.strip() for n in srcs_m.group(1).split() if n.strip()]

            violations.append(
                {
                    "kind": "drc_violation",
                    "violation_type": type_m.group(1).strip(),
                    "nets": nets[:20],
                    "layer": layer_m.group(1) if layer_m else None,
                    "bbox_wkt": (
                        f"POLYGON(({x1} {y1}, {x2} {y1}, {x2} {y2}, {x1} {y2}, {x1} {y1}))"
                        if all(v is not None for v in [x1, y1, x2, y2])
                        else None
                    ),
                }
            )
        return violations
