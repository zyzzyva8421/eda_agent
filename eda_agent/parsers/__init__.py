"""parsers sub-package – structured report extraction.

Usage
-----
    from eda_agent.parsers import get_parser

    parser = get_parser("timing")
    records = parser.parse_file(Path("route.rpt"))
"""

from __future__ import annotations

from eda_agent.parsers.base import BaseParser, ParseError
from eda_agent.parsers.congestion import CongestionParser
from eda_agent.parsers.drc import DRCParser
from eda_agent.parsers.innovus_drc import InnovusDRCParser
from eda_agent.parsers.innovus_power import InnovusPowerParser
from eda_agent.parsers.innovus_timing import InnovusTimingParser
from eda_agent.parsers.innovus_utilization import InnovusUtilizationParser
from eda_agent.parsers.power import PowerParser
from eda_agent.parsers.timing import TimingParser
from eda_agent.parsers.utilization import UtilizationParser

_PARSER_REGISTRY: dict[str, BaseParser] = {
    "timing": TimingParser(),
    "congestion": CongestionParser(),
    "utilization": UtilizationParser(),
    "power": PowerParser(),
    "drc": DRCParser(),
    "innovus_timing": InnovusTimingParser(),
    "innovus_power": InnovusPowerParser(),
    "innovus_utilization": InnovusUtilizationParser(),
    "innovus_drc": InnovusDRCParser(),
}


def get_parser(report_type: str) -> BaseParser:
    """Return the parser for *report_type*.

    Raises
    ------
    KeyError
        If no parser is registered for that type.
    """
    try:
        return _PARSER_REGISTRY[report_type.lower()]
    except KeyError:
        available = list(_PARSER_REGISTRY.keys())
        raise KeyError(
            f"No parser for report_type '{report_type}'. Available: {available}"
        ) from None


def register_parser(parser: BaseParser) -> None:
    """Register a custom parser at runtime."""
    _PARSER_REGISTRY[parser.report_type.lower()] = parser


__all__ = [
    "BaseParser",
    "ParseError",
    "TimingParser",
    "CongestionParser",
    "UtilizationParser",
    "PowerParser",
    "DRCParser",
    "InnovusTimingParser",
    "InnovusPowerParser",
    "InnovusUtilizationParser",
    "InnovusDRCParser",
    "get_parser",
    "register_parser",
]
