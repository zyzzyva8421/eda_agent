"""Innovus congestion hotspot map parser.

This parser extracts hotspot bounding boxes from map-like congestion reports,
including outputs from ``reportCongestion -hotSpot`` and similar formats.
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

_BBOX_WITH_OVERFLOW = re.compile(
    r"""
    (?:bbox|box)?\s*[:=]?\s*
    \(?\s*([-\d.]+)\s*,?\s+([-\d.]+)\s*\)?\s*
    (?:-|to)\s*
    \(?\s*([-\d.]+)\s*,?\s+([-\d.]+)\s*\)?     # x2 y2
    .*?
    overflow\s*[:=]?\s*([-\d.]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


class InnovusCongestionMapParser(BaseParser):
    """Parse Innovus congestion hotspot map text into hotspot records."""

    report_type = "innovus_congestion_map"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for match in _BBOX_WITH_OVERFLOW.finditer(text):
            x1, y1, x2, y2, overflow = match.groups()
            x1f = float(x1)
            y1f = float(y1)
            x2f = float(x2)
            y2f = float(y2)
            if x2f <= x1f or y2f <= y1f:
                continue
            records.append(
                {
                    "kind": "hotspot",
                    "wkt": (
                        f"POLYGON(({x1f} {y1f}, {x2f} {y1f}, "
                        f"{x2f} {y2f}, {x1f} {y2f}, {x1f} {y1f}))"
                    ),
                    "x1": x1f,
                    "y1": y1f,
                    "x2": x2f,
                    "y2": y2f,
                    "overflow": int(float(overflow)),
                }
            )

        if not records:
            raise ParseError("No Innovus congestion hotspot map data found in report text.")
        return records
