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
#   wns max -1.76
#   tns -12.451
#   tns max -77.03
#   violating paths 7
_SUMMARY_WNS = re.compile(r"^wns(?:\s+max)?\s+(-?\d+\.\d+)", re.MULTILINE | re.IGNORECASE)
_SUMMARY_TNS = re.compile(r"^tns(?:\s+max)?\s+(-?\d+\.\d+)", re.MULTILINE | re.IGNORECASE)
_SUMMARY_FEP = re.compile(
    r"^(?:violating\s+paths|failing\s+paths)\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_SUMMARY_WORST_SLACK = re.compile(
    r"^worst\s+slack(?:\s+max)?\s+(-?\d+\.\d+)",
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
    r"^Startpoint:\s+(.+?)(?:\s+\(|$)$", re.MULTILINE | re.IGNORECASE
)
_PATH_ENDPOINT = re.compile(
    r"^Endpoint:\s+(.+?)(?:\s+\(|$)$", re.MULTILINE | re.IGNORECASE
)
_PATH_GROUP = re.compile(
    r"^Path\s+Group:\s+(.+)$", re.MULTILINE | re.IGNORECASE
)
# Match slack line - format is "  -0.59   slack (VIOLATED)" with leading spaces
_PATH_SLACK = re.compile(
    r"^\s*-?\d+\.\d+\s+slack\s+\((?:MET|VIOLATED)\)",
    re.MULTILINE | re.IGNORECASE,
)
# Fallback: find any slack value in the block - look for negative number followed by slack
_PATH_SLACK_FALLBACK = re.compile(
    r"(-?\d+\.\d+)\s+slack",
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
        worst_slack_m = _SUMMARY_WORST_SLACK.search(text)
        if not any([wns_m, tns_m, fep_m, worst_slack_m]):
            return None

        view_m = _SUMMARY_VIEW.search(text)
        # Use wns, or fall back to worst_slack if wns not found
        wns_value = None
        if wns_m:
            wns_value = float(wns_m.group(1))
        elif worst_slack_m:
            wns_value = float(worst_slack_m.group(1))

        return {
            "kind": "summary",
            "view": view_m.group(1) if view_m else "default",
            "wns_ns": wns_value,
            "tns_ns": float(tns_m.group(1)) if tns_m else None,
            "failing_endpoints": int(fep_m.group(1)) if fep_m else None,
        }

    def _parse_paths(self, text: str) -> list[dict[str, Any]]:
        """Parse timing paths by searching globally for startpoint/endpoint/slack across the text.

        OpenROAD timing reports may have path definition and slack in different sections,
        so we search globally and pair them by proximity.
        """
        import re
        paths = []

        # Find all startpoints
        for sp_match in _PATH_STARTPOINT.finditer(text):
            sp = sp_match.group(1).strip()
            sp_start = sp_match.start()

            # Find endpoint after this startpoint (within ~2000 chars)
            ep_match = _PATH_ENDPOINT.search(text[sp_start:sp_start+2000])
            if not ep_match:
                continue
            ep = ep_match.group(1).strip()

            # Find path group
            text_after = text[sp_start:sp_start+2000]
            gr_match = _PATH_GROUP.search(text_after)
            gr = gr_match.group(1).strip() if gr_match else None

            # Find slack value - first try VIOLATED pattern
            sl_match = _PATH_SLACK.search(text_after)
            if not sl_match:
                sl_match = _PATH_SLACK_FALLBACK.search(text_after)

            if sl_match:
                match_line = sl_match.group(0)
                val_match = re.search(r'-?\d+\.\d+', match_line)
                if val_match:
                    slack_val = float(val_match.group(0))
                    paths.append({
                        "kind": "path",
                        "startpoint": sp,
                        "endpoint": ep,
                        "path_group": gr,
                        "slack_ns": slack_val,
                    })

        return paths
