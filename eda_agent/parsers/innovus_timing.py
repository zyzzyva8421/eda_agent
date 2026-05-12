"""Innovus timing report parser (separate from ORFS/OpenROAD parser)."""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

_VIEW = re.compile(r"^Analysis\s+View:\s+(\S+)", re.MULTILINE | re.IGNORECASE)
_SLACK_TIME = re.compile(r"^=\s+Slack\s+Time\s+(-?\d+\.\d+)", re.MULTILINE | re.IGNORECASE)
_BEGINPOINT = re.compile(r"^Beginpoint:\s+(.+?)(?:\s+\(|$)$", re.MULTILINE | re.IGNORECASE)
_ENDPOINT = re.compile(r"^Endpoint:\s+(.+?)(?:\s+\(|$)$", re.MULTILINE | re.IGNORECASE)
_PATH_GROUPS = re.compile(r"^Path\s+Groups:\s+\{?(.+?)\}?$", re.MULTILINE | re.IGNORECASE)


class InnovusTimingParser(BaseParser):
    """Parse Innovus timing report into timing summary/path records."""

    report_type = "innovus_timing"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        slack_m = _SLACK_TIME.search(text)
        if slack_m:
            view_m = _VIEW.search(text)
            records.append(
                {
                    "kind": "summary",
                    "view": view_m.group(1) if view_m else "default",
                    "wns_ns": float(slack_m.group(1)),
                    "tns_ns": None,
                    "failing_endpoints": None,
                }
            )

        begin_m = _BEGINPOINT.search(text)
        end_m = _ENDPOINT.search(text)
        group_m = _PATH_GROUPS.search(text)
        if begin_m and end_m and slack_m:
            records.append(
                {
                    "kind": "path",
                    "startpoint": begin_m.group(1).strip(),
                    "endpoint": end_m.group(1).strip(),
                    "path_group": group_m.group(1).strip() if group_m else None,
                    "slack_ns": float(slack_m.group(1)),
                }
            )

        if not records:
            raise ParseError("No Innovus timing data found in report text.")
        return records
