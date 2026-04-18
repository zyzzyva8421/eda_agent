"""Base classes for report parsers.

Each parser takes the raw text of a report file and returns a structured
Python dictionary (or list of dicts) that can be inserted into the database.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any


class ParseError(Exception):
    """Raised when a parser cannot extract meaningful data from the input."""


class BaseParser(abc.ABC):
    """Abstract base for all report parsers."""

    #: Type tag that this parser handles, e.g. 'timing', 'congestion'
    report_type: str = ""

    def parse_file(self, path: Path) -> list[dict[str, Any]]:
        """Read *path* and return parsed records.

        Raises
        ------
        ParseError
            If the file cannot be parsed.
        """
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ParseError(f"Cannot read {path}: {exc}") from exc
        return self.parse_text(text)

    @abc.abstractmethod
    def parse_text(self, text: str) -> list[dict[str, Any]]:
        """Parse raw report text and return a list of record dicts.

        Each dict maps column names → values and will be bulk-inserted into
        the corresponding database table.
        """
