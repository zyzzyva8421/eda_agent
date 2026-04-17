"""Timing report parser.

Supports two output formats produced by ORFS / OpenROAD:

1. **Summary report** (``report_checks -path_delay min_max``)
   – extracts WNS, TNS, failing endpoint count (FEP) per corner/view.

2. **Path detail report** (``report_checks -path_delay max -format full``)
   – extracts each violated timing path (startpoint, endpoint, slack, …).
"""

from __future__ import annotations

import re
from typing import Any

from eda_agent.parsers.base import BaseParser, ParseError

# ── Summary patterns ──────────────────────────────────────────────────────────

# Matches lines like:
#   wns -0.342
#   tns -12.451
#   violating paths 7
_SUMMARY_WNS = re.compile(r"^wns\s+(-?\d+\.\d+)", re.MULTILINE | re.IGNORECASE)
_SUMMARY_TNS = re.compile(r"^tns\s+(-?\d+\.\d+)", re.MULTILINE | re.IGNORECASE)
_SUMMARY_FEP = re.compile(
    r"^(?:violating\s+paths|failing\s+paths)\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_SUMMARY_VIEW = re.compile(
    r"^(?:view|corner|analysis\s+view)[:=\s]+(\S+)",
    re.MULTILINE | re.IGNORECASE,
)

# ── Path-detail patterns ──────────────────────────────────────────────────────

# Block separator (OpenROAD separates paths with dashes or ======)
_PATH_SEP = re.compile(r"-{40,}|={40,}")

_PATH_STARTPOINT = re.compile(
    r"^Startpoint:\s+(.+)$", re.MULTILINE | re.IGNORECASE
)
_PATH_ENDPOINT = re.compile(
    r"^Endpoint:\s+(.+)$", re.MULTILINE | re.IGNORECASE
)
_PATH_GROUP = re.compile(
    r"^Path\s+Group:\s+(.+)$", re.MULTILINE | re.IGNORECASE
)
_PATH_SLACK = re.compile(
    r"^(?:slack|data\s+arrival\s+time.*?slack)[^\d-]*(-?\d+\.\d+)",
    re.MULTILINE | re.IGNORECASE,
)
# More specific slack line (last number on the "slack (VIOLATED)" line)
_PATH_SLACK_VIOLATED = re.compile(
    r"slack\s+\((?:MET|VIOLATED)\)\s+(-?\d+\.\d+)",
    re.MULTILINE | re.IGNORECASE,
)


class TimingParser(BaseParser):
    """Parse OpenROAD timing reports into summary and path records."""

    report_type = "timing"

    def parse_text(self, text: str) -> list[dict[str, Any]]:
        """Return a mixed list of ``{"kind": "summary", ...}`` and
        ``{"kind": "path", ...}`` dicts.
        """
        records: list[dict[str, Any]] = []
        summary = self._parse_summary(text)
        if summary:
            records.append(summary)
        records.extend(self._parse_paths(text))
        if not records:
            raise ParseError("No timing data found in report text.")
        return records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_summary(self, text: str) -> dict[str, Any] | None:
        wns_m = _SUMMARY_WNS.search(text)
        tns_m = _SUMMARY_TNS.search(text)
        fep_m = _SUMMARY_FEP.search(text)
        if not any([wns_m, tns_m, fep_m]):
            return None

        view_m = _SUMMARY_VIEW.search(text)
        return {
            "kind": "summary",
            "view": view_m.group(1) if view_m else "default",
            "wns_ns": float(wns_m.group(1)) if wns_m else None,
            "tns_ns": float(tns_m.group(1)) if tns_m else None,
            "failing_endpoints": int(fep_m.group(1)) if fep_m else None,
        }

    def _parse_paths(self, text: str) -> list[dict[str, Any]]:
        blocks = _PATH_SEP.split(text)
        paths = []
        for block in blocks:
            if "Startpoint" not in block:
                continue
            sp_m = _PATH_STARTPOINT.search(block)
            ep_m = _PATH_ENDPOINT.search(block)
            gr_m = _PATH_GROUP.search(block)
            # Prefer the explicit "(VIOLATED)" pattern; fall back to generic
            sl_m = _PATH_SLACK_VIOLATED.search(block) or _PATH_SLACK.search(block)

            if sp_m and ep_m and sl_m:
                paths.append(
                    {
                        "kind": "path",
                        "startpoint": sp_m.group(1).strip(),
                        "endpoint": ep_m.group(1).strip(),
                        "path_group": gr_m.group(1).strip() if gr_m else None,
                        "slack_ns": float(sl_m.group(1)),
                    }
                )
        return paths
