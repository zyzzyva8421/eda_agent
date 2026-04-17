"""ICC2 backend stub.

Not yet implemented.  Fill in the implementation when adapting to
Synopsys IC Compiler 2.
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

_ICC2_STAGES = [
    "floorplan",
    "place",
    "cts",
    "route",
    "signoff",
]


class ICC2Backend(AbstractEDABackend):
    """Synopsys IC Compiler 2 backend – **not yet implemented (stub)**."""

    @property
    def name(self) -> str:
        return "icc2"

    @property
    def version(self) -> str:
        return "stub"

    def get_supported_stages(self) -> list[str]:
        return list(_ICC2_STAGES)

    def is_available(self) -> bool:
        return False  # Stub: always unavailable until implemented

    def run_stage(
        self,
        stage: str,
        design: DesignSpec,
        params: dict[str, Any],
    ) -> RunResult:
        raise NotImplementedError(
            "ICC2Backend is not yet implemented. "
            "Implement run_stage() to integrate with Synopsys IC Compiler 2."
        )

    def collect_reports(self, result: RunResult) -> list[ReportFile]:
        raise NotImplementedError("ICC2Backend is not yet implemented.")
