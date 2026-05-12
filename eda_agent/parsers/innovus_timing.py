"""Innovus timing report parser (separate from ORFS/OpenROAD parser).

Supports Innovus 18.x report_timing output which lists individual paths.
Each path block has the format::

    Path N: MET/VIOLATED <check type>
    Endpoint:   <pin>   (edge) checked with ...
    Beginpoint: <pin>   (edge) triggered by ...
    Path Groups: {<group>}
    Analysis View: <view>
    ...
    = Slack Time    <value>

The parser collects ALL paths, derives WNS (minimum slack), TNS (sum of
negative slacks), failing endpoint count, and returns one summary record
plus one record per path.
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# Path separator: "Path N:"
_PATH_HEADER = re.compile(r"^Path\s+\d+:", re.MULTILINE)

# Within a path block
_SLACK_LINE = re.compile(
    r"[=\s]\s*Slack\s+Time\s+(-?\d+(?:\.\d+)?)", re.MULTILINE | re.IGNORECASE
)
_BEGINPOINT = re.compile(r"^Beginpoint:\s+(.+?)(?:\s+\(|$)", re.MULTILINE | re.IGNORECASE)
_ENDPOINT   = re.compile(r"^Endpoint:\s+(.+?)(?:\s+\(|$)", re.MULTILINE | re.IGNORECASE)
_PATH_GROUP = re.compile(r"^Path\s+Groups:\s+\{?(.+?)\}?\s*$", re.MULTILINE | re.IGNORECASE)
_VIEW       = re.compile(r"^Analysis\s+View:\s+(\S+)", re.MULTILINE | re.IGNORECASE)
_MET_VIOL   = re.compile(r"^Path\s+\d+:\s+(MET|VIOLATED)", re.MULTILINE | re.IGNORECASE)


def _split_paths(text: str) -> list[str]:
    """Split the report text into individual path blocks."""
    spans = [m.start() for m in _PATH_HEADER.finditer(text)]
    if not spans:
        return []
    blocks = []
    for i, start in enumerate(spans):
        end = spans[i + 1] if i + 1 < len(spans) else len(text)
        blocks.append(text[start:end])
    return blocks


class InnovusTimingParser(BaseParser):
    """Parse Innovus timing report into timing summary/path records."""

    report_type = "innovus_timing"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        blocks = _split_paths(text)
        if not blocks:
            raise ParseError("No Innovus timing path data found in report text.")

        records: list[dict[str, Any]] = []
        slacks: list[float] = []

        # Use the first analysis view found in the whole file
        view_m = _VIEW.search(text)
        default_view = view_m.group(1) if view_m else "default"

        for block in blocks:
            slack_m = _SLACK_LINE.search(block)
            if slack_m is None:
                continue
            slack = float(slack_m.group(1))
            slacks.append(slack)

            begin_m = _BEGINPOINT.search(block)
            end_m   = _ENDPOINT.search(block)
            grp_m   = _PATH_GROUP.search(block)
            view_bm = _VIEW.search(block)

            records.append(
                {
                    "kind": "path",
                    "startpoint":  begin_m.group(1).strip() if begin_m else None,
                    "endpoint":    end_m.group(1).strip()   if end_m   else None,
                    "path_group":  grp_m.group(1).strip()   if grp_m   else None,
                    "view":        view_bm.group(1) if view_bm else default_view,
                    "slack_ns":    slack,
                    "violated":    slack < 0,
                }
            )

        if not slacks:
            raise ParseError("No slack values found in Innovus timing report.")

        failing = [s for s in slacks if s < 0]
        wns = min(slacks)
        tns = sum(failing) if failing else 0.0

        summary: dict[str, Any] = {
            "kind": "summary",
            "view": default_view,
            "wns_ns": wns,
            "tns_ns": tns,
            "failing_endpoints": len(failing),
            "total_paths": len(slacks),
        }
        return [summary] + records
