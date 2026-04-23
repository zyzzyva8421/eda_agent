"""Congestion report parser.

Parses the global-routing congestion report produced by OpenROAD
(``report_congestion``) and ORFS.

Expected format (excerpt)::

    Global Routing Congestion Report
    ---------------------------------
    Layer  Direction  Overflow  Max H/V Usage  Available  Resources
    metal1  H         0         0.85          120        141
    metal2  V         3         0.92           98        107
    ...
    Total overflow: 3
    Worst congestion tile: (42, 17) to (43, 18)  overflow=2

The parser also handles a simpler "GRT" summary block with just two numbers
(horizontal overflow, vertical overflow) when no layer detail is present.
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# ── Layer table patterns ──────────────────────────────────────────────────────

# Matches a data row in the per-layer congestion table, e.g.:
#   metal2  V  3  0.92  98  107
_LAYER_ROW = re.compile(
    r"^(metal\w+|M\d+)\s+(H|V)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# Total overflow summary line
_TOTAL_OVERFLOW = re.compile(
    r"total\s+overflow[:\s]+(\d+)", re.MULTILINE | re.IGNORECASE
)

# Worst congestion tile with bounding box
_WORST_TILE = re.compile(
    r"worst\s+congestion\s+tile[:\s]+\((\d+)[,\s]+(\d+)\)\s+to\s+\((\d+)[,\s]+(\d+)\)"
    r".*?overflow=(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# GRT summary (two-number form):  "GRT: H overflow 5  V overflow 2"
_GRT_SIMPLE = re.compile(
    r"H\s+overflow\s+(\d+)\s+V\s+overflow\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# Average / max utilisation from density report
_UTIL_AVG = re.compile(
    r"average\s+(?:routing\s+)?utilization[:\s]+([\d.]+)%?",
    re.MULTILINE | re.IGNORECASE,
)
_UTIL_MAX = re.compile(
    r"max(?:imum)?\s+(?:routing\s+)?utilization[:\s]+([\d.]+)%?",
    re.MULTILINE | re.IGNORECASE,
)

# ── ORFS violation format ─────────────────────────────────────────────────────
# violation type: Horizontal/Vertical congestion
#         srcs: net:net_foo ...
#         comment: capacity:N usage:M overflow:K
#         bbox = (x1, y1) - (x2, y2) on Layer LAYER
_VIOLATION_TYPE = re.compile(
    r"violation\s+type[:\s]+(horizontal|vertical)\s+congestion",
    re.MULTILINE | re.IGNORECASE,
)
_VIOLATION_SRCS = re.compile(
    r"srcs[:\s]+(.+?)(?=\n\s*(?:bbox|comment|violation|$))",
    re.MULTILINE,
)
_VIOLATION_COMMENT = re.compile(
    r"comment[:\s]+capacity:(\d+)\s+usage:(\d+)\s+overflow:(\d+)",
    re.IGNORECASE,
)
_VIOLATION_BBOX = re.compile(
    r"bbox\s*=\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*-\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
    re.IGNORECASE,
)
_VIOLATION_LAYER = re.compile(
    r"on\s+Layer\s+(\S+)", re.IGNORECASE,
)


class CongestionParser(BaseParser):
    """Parse OpenROAD / ORFS congestion reports."""

    report_type = "congestion"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        summary = self._parse_summary(text)
        if summary:
            records.append(summary)

        hotspots = self._parse_hotspots(text)
        records.extend(hotspots)

        layer_stats = self._parse_layers(text)
        records.extend(layer_stats)

        orfs_violations = self._parse_orfs_violations(text)
        records.extend(orfs_violations)

        if not records:
            raise ParseError("No congestion data found in report text.")
        return records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_summary(self, text: str) -> dict[str, Any] | None:
        total_m = _TOTAL_OVERFLOW.search(text)
        grt_m = _GRT_SIMPLE.search(text)
        avg_m = _UTIL_AVG.search(text)
        max_m = _UTIL_MAX.search(text)

        if not any([total_m, grt_m, avg_m, max_m]):
            return None

        h_overflow = int(grt_m.group(1)) if grt_m else None
        v_overflow = int(grt_m.group(2)) if grt_m else None
        total_overflow = (
            int(total_m.group(1))
            if total_m
            else (
                (h_overflow or 0) + (v_overflow or 0)
                if h_overflow is not None
                else None
            )
        )

        return {
            "kind": "summary",
            "total_overflow": total_overflow,
            "h_overflow": h_overflow,
            "v_overflow": v_overflow,
            "avg_utilization_pct": float(avg_m.group(1)) if avg_m else None,
            "max_utilization_pct": float(max_m.group(1)) if max_m else None,
        }

    def _parse_hotspots(self, text: str) -> list[dict[str, Any]]:
        hotspots = []
        for m in _WORST_TILE.finditer(text):
            x1, y1, x2, y2, overflow = (int(g) for g in m.groups())
            hotspots.append(
                {
                    "kind": "hotspot",
                    # WKT polygon for PostGIS insertion
                    "wkt": (
                        f"POLYGON(({x1} {y1}, {x2} {y1}, "
                        f"{x2} {y2}, {x1} {y2}, {x1} {y1}))"
                    ),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "overflow": overflow,
                }
            )
        return hotspots

    def _parse_layers(self, text: str) -> list[dict[str, Any]]:
        layers = []
        for m in _LAYER_ROW.finditer(text):
            layer, direction, overflow, utilization, used, available = m.groups()
            layers.append(
                {
                    "kind": "layer",
                    "layer": layer,
                    "direction": direction.upper(),
                    "overflow": int(overflow),
                    "utilization": float(utilization),
                    "used_tracks": int(used),
                    "available_tracks": int(available),
                }
            )
        return layers

    def _parse_orfs_violations(self, text: str) -> list[dict[str, Any]]:
        """Parse ORFS violation report format (congestion-*.rpt files)."""
        violations = []
        blocks = re.split(r"violation type:", text)
        for block in blocks[1:]:  # skip first split (before any "violation type:")
            block = "violation type:" + block  # re-add the header
            type_m = _VIOLATION_TYPE.search(block)
            srcs_m = _VIOLATION_SRCS.search(block)
            comment_m = _VIOLATION_COMMENT.search(block)
            bbox_m = _VIOLATION_BBOX.search(block)
            layer_m = _VIOLATION_LAYER.search(block)

            if not type_m:
                continue

            direction = type_m.group(1).upper()
            capacity = int(comment_m.group(1)) if comment_m else None
            usage = int(comment_m.group(2)) if comment_m else None
            overflow = int(comment_m.group(3)) if comment_m else None
            x1 = float(bbox_m.group(1)) if bbox_m else None
            y1 = float(bbox_m.group(2)) if bbox_m else None
            x2 = float(bbox_m.group(3)) if bbox_m else None
            y2 = float(bbox_m.group(4)) if bbox_m else None
            layer = layer_m.group(1) if layer_m else None

            # Parse nets from srcs line
            nets = []
            if srcs_m:
                # Format: "net:_02527_ net:_10757_ ..." or just names
                nets = [n.strip() for n in srcs_m.group(1).split() if n.strip()]

            violations.append(
                {
                    "kind": "orfs_violation",
                    "direction": direction,
                    "capacity": capacity,
                    "usage": usage,
                    "overflow": overflow,
                    "nets": nets[:20],  # cap at 20 nets per violation
                    "wkt": (
                        f"POLYGON(({x1} {y1}, {x2} {y1}, {x2} {y2}, {x1} {y2}, {x1} {y1}))"
                        if all([x1, y1, x2, y2])
                        else None
                    ),
                    "layer": layer,
                }
            )
        return violations
