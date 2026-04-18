"""Innovus backend stub.

Not yet implemented.  A placeholder so that the backend registry and
configuration layer recognise Innovus as a valid backend name and can
display it in the UI / API.  Fill in the implementation when adapting to
Cadence Innovus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eda_agent.backends.base import (
    AbstractEDABackend,
    DesignSpec,
    ReportFile,
    RunResult,
    StageStatus,
)

_INNOVUS_STAGES = [
    "synth",          # typically handled by Genus; included for symmetry
    "floorplan",
    "powerplan",
    "place",
    "cts",
    "route",
    "signoff",
]


class InnovusBackend(AbstractEDABackend):
    """Cadence Innovus backend – **not yet implemented (stub)**."""

    @property
    def name(self) -> str:
        return "innovus"

    @property
    def version(self) -> str:
        return "stub"

    def get_supported_stages(self) -> list[str]:
        return list(_INNOVUS_STAGES)

    def is_available(self) -> bool:
        return False  # Stub: always unavailable until implemented

    def run_stage(
        self,
        stage: str,
        design: DesignSpec,
        params: dict[str, Any],
    ) -> RunResult:
        raise NotImplementedError(
            "InnovusBackend is not yet implemented. "
            "Implement run_stage() to integrate with Cadence Innovus."
        )

    def collect_reports(self, result: RunResult) -> list[ReportFile]:
        raise NotImplementedError("InnovusBackend is not yet implemented.")
