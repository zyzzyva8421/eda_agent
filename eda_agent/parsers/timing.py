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
# Match slack line – two formats produced by different OpenROAD versions:
#   Format A (value before keyword):  "  -0.59   slack (VIOLATED)"
#   Format B (value after keyword):   "slack (VIOLATED) -0.342"
#   Also handle: "slack (MET) 0.35" with potential leading whitespace
_PATH_SLACK = re.compile(
    r"^\s*-?\d+\.\d+\s+slack\s+\((?:MET|VIOLATED)\)"
    r"|slack\s+\((?:MET|VIOLATED)\)\s+-?\d+\.\d+"
    r"|slack\s+\((?:MET|VIOLATED)\)\s+\n\s*-?\d+\.\d+",
    re.MULTILINE | re.IGNORECASE,
)
# Fallback: extract the numeric slack value from whichever format matched
_PATH_SLACK_VALUE = re.compile(r"-?\d+\.\d+")
# Fallback: find any slack value in the block (handles multiline format)
_PATH_SLACK_FALLBACK = re.compile(
    r"(-?\d+\.\d+)\s+slack|slack\s+\((?:MET|VIOLATED)\)\s+(-?\d+\.\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# ── ORFS extended metrics patterns ──────────────────────────────────────────

# Clock period / fmax: "clk period_min = 4.19 fmax = 238.86"
_FMAX = re.compile(r"fmax\s*=\s*([\d.]+)", re.IGNORECASE)

# Clock skew: "  -0.24 setup skew"
_CLOCK_SKEW = re.compile(r"setup\s+skew\s*[-–]?\s*([\d.]+)", re.MULTILINE | re.IGNORECASE)

# Violation counts: "max slew violation count 0"
_SLEW_VIO = re.compile(
    r"max\s+slew\s+violation\s+count\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_FANOUT_VIO = re.compile(
    r"max\s+fanout\s+violation\s+count\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_CAP_VIO = re.compile(
    r"max\s+cap(?:acitance)?\s+violation\s+count\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_SETUP_VIO = re.compile(
    r"setup\s+violation\s+count\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
_HOLD_VIO = re.compile(
    r"hold\s+violation\s+count\s+(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# Critical path delay: "critical path delay" followed by value
_CPD = re.compile(r"^critical\s+path\s+delay\s*\n\s*([\d.]+)", re.MULTILINE | re.IGNORECASE)

# Slack / critical path ratio
_SLACK_CPD_RATIO = re.compile(
    r"slack\s+div\s+critical\s+path\s+delay\s*\n\s*([\d.]+)",
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
        fmax_m = _FMAX.search(text)
        skew_m = _CLOCK_SKEW.search(text)
        slew_vio_m = _SLEW_VIO.search(text)
        fanout_vio_m = _FANOUT_VIO.search(text)
        cap_vio_m = _CAP_VIO.search(text)
        setup_vio_m = _SETUP_VIO.search(text)
        hold_vio_m = _HOLD_VIO.search(text)
        cpd_m = _CPD.search(text)
        ratio_m = _SLACK_CPD_RATIO.search(text)
        view_m = _SUMMARY_VIEW.search(text)

        if not any([
            wns_m, tns_m, fep_m, worst_slack_m,
            fmax_m, skew_m, slew_vio_m, fanout_vio_m,
            cap_vio_m, setup_vio_m, hold_vio_m,
            cpd_m, ratio_m,
        ]):
            return None

        wns_value = None
        if wns_m:
            wns_value = float(wns_m.group(1))
        elif worst_slack_m:
            wns_value = float(worst_slack_m.group(1))

        def _int(m: re.Match | None) -> int | None:
            return int(m.group(1)) if m else None

        def _float(m: re.Match | None) -> float | None:
            return float(m.group(1)) if m else None

        return {
            "kind": "summary",
            "view": view_m.group(1) if view_m else "default",
            "wns_ns": wns_value,
            "tns_ns": _float(tns_m),
            "failing_endpoints": _int(fep_m),
            # ORFS extended metrics
            "fmax_mhz": _float(fmax_m),
            "clock_skew_ns": _float(skew_m),
            "max_slew_violations": _int(slew_vio_m),
            "max_fanout_violations": _int(fanout_vio_m),
            "max_cap_violations": _int(cap_vio_m),
            "setup_violations": _int(setup_vio_m),
            "hold_violations": _int(hold_vio_m),
            "critical_path_delay_ns": _float(cpd_m),
            "slack_cpd_ratio_pct": _float(ratio_m),
        }

    def _parse_paths(self, text: str) -> list[dict[str, Any]]:
        """Parse timing paths by searching globally for startpoint/endpoint/slack across the text.

        OpenROAD timing reports may have path definition and slack in different sections,
        so we search globally and pair them by proximity.
        """
        paths = []
        
        # First, find all path section boundaries (separated by === or ----)
        # This is more reliable than fixed character counts
        section_starts = [m.start() for m in _PATH_STARTPOINT.finditer(text)]
        
        for i, sp_match in enumerate(_PATH_STARTPOINT.finditer(text)):
            sp = sp_match.group(1).strip()
            sp_start = sp_match.start()

            # Find endpoint after this startpoint in the same section
            # Use the next startpoint position as section boundary, or end of text
            if i + 1 < len(section_starts):
                section_end = section_starts[i + 1]
            else:
                section_end = len(text)
            
            # Search within this section for endpoint
            section_text = text[sp_start:section_end]
            ep_match = _PATH_ENDPOINT.search(section_text)
            if not ep_match:
                continue
            ep = ep_match.group(1).strip()

            # Find path group
            gr_match = _PATH_GROUP.search(section_text)
            gr = gr_match.group(1).strip() if gr_match else None

            # Find slack value - first try primary VIOLATED/MET pattern
            sl_match = _PATH_SLACK.search(section_text)
            slack_val: float | None = None
            if sl_match:
                # Extract numeric value from whichever format matched
                vals = _PATH_SLACK_VALUE.findall(sl_match.group(0))
                if vals:
                    slack_val = float(vals[0])
            else:
                fb_match = _PATH_SLACK_FALLBACK.search(section_text)
                if fb_match:
                    # Group 1 = "value slack", group 2 = "slack (MET/VIOLATED) value"
                    raw = fb_match.group(1) or fb_match.group(2)
                    if raw:
                        slack_val = float(raw)

            if slack_val is not None:
                paths.append({
                    "kind": "path",
                    "startpoint": sp,
                    "endpoint": ep,
                    "path_group": gr,
                    "slack_ns": slack_val,
                })

        return paths
