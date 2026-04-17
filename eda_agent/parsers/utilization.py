r"""Utilization / area report parser.

Parses the cell / area utilization report produced by OpenROAD
(``report_design_area``, ``report_cell_usage``) and Yosys (``stat``).

Typical OpenROAD design-area output::

    Design area 43210 u^2 42% utilization.

Typical Yosys stat output::

    Chip area for module '\gcd': 2091.776000
    ...
    Number of cells: 247
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# ── Patterns ──────────────────────────────────────────────────────────────────

# OpenROAD design area + utilization on one line
_DESIGN_AREA = re.compile(
    r"Design\s+area\s+([\d.]+)\s+u\^2\s+([\d.]+)%\s+utilization",
    re.IGNORECASE,
)

# Yosys module area
_YOSYS_AREA = re.compile(
    r"Chip\s+area\s+for\s+(?:module|top\s+module)[^:]*:\s*([\d.]+)",
    re.IGNORECASE,
)

# Number of cells
_NUM_CELLS = re.compile(
    r"Number\s+of\s+cells[:\s]+([\d,]+)", re.IGNORECASE
)

# Number of registers / flops
_NUM_REGS = re.compile(
    r"Number\s+of\s+(?:registers?|flops?)[:\s]+([\d,]+)", re.IGNORECASE
)

# Individual cell type row (Yosys): "   $dff  47"
_CELL_TYPE_ROW = re.compile(
    r"^\s+(\$\w+|\w+)\s+(\d+)\s*$", re.MULTILINE
)


class UtilizationParser(BaseParser):
    """Parse OpenROAD / Yosys utilization and area reports."""

    report_type = "utilization"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        summary = self._parse_summary(text)
        if summary:
            records.append(summary)

        cell_types = self._parse_cell_types(text)
        records.extend(cell_types)

        if not records:
            raise ParseError("No utilization data found in report text.")
        return records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_summary(self, text: str) -> dict[str, Any] | None:
        area_m = _DESIGN_AREA.search(text) or _YOSYS_AREA.search(text)
        cells_m = _NUM_CELLS.search(text)
        regs_m = _NUM_REGS.search(text)

        if not any([area_m, cells_m, regs_m]):
            return None

        # Design area line gives both area and utilization
        if _DESIGN_AREA.search(text):
            da = _DESIGN_AREA.search(text)
            area_um2 = float(da.group(1))
            util_pct = float(da.group(2))
        elif area_m:
            area_um2 = float(area_m.group(1))
            util_pct = None
        else:
            area_um2 = None
            util_pct = None

        def _parse_int(m: re.Match | None) -> int | None:
            if m is None:
                return None
            return int(m.group(1).replace(",", ""))

        return {
            "kind": "summary",
            "design_area_um2": area_um2,
            "utilization_pct": util_pct,
            "num_cells": _parse_int(cells_m),
            "num_registers": _parse_int(regs_m),
        }

    def _parse_cell_types(self, text: str) -> list[dict[str, Any]]:
        records = []
        for m in _CELL_TYPE_ROW.finditer(text):
            cell_type, count = m.group(1), int(m.group(2))
            records.append(
                {
                    "kind": "cell_type",
                    "cell_type": cell_type,
                    "count": count,
                }
            )
        return records
