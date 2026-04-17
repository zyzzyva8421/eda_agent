"""ORFS (OpenROAD Flow Scripts) backend implementation.

Invokes ``make`` in ``$ORFS_ROOT/flow`` with the appropriate target and
design configuration, captures logs, and indexes output reports.
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eda_agent.backends.base import (
    AbstractEDABackend,
    DesignSpec,
    ReportFile,
    RunResult,
    StageStatus,
)
from eda_agent.config import settings

logger = logging.getLogger(__name__)

# Ordered ORFS flow stages
ORFS_STAGES: list[str] = [
    "synth",
    "floorplan",
    "place",
    "cts",
    "route",
    "finish",
]

# Map EDA stage names → ORFS make targets
_STAGE_TARGETS: dict[str, str] = {
    "synth": "synth",
    "floorplan": "floorplan",
    "place": "place",
    "cts": "cts",
    "route": "route",
    "finish": "finish",
}

# Report filename patterns per stage (relative to the ORFS results dir)
_REPORT_PATTERNS: dict[str, list[tuple[str, str]]] = {
    # stage → list of (glob_pattern, report_type)
    "synth": [
        ("*.rpt", "timing"),
        ("*area*.rpt", "utilization"),
    ],
    "floorplan": [
        ("*floorplan*.rpt", "utilization"),
    ],
    "place": [
        ("*place*.rpt", "timing"),
        ("*congestion*.rpt", "congestion"),
    ],
    "cts": [
        ("*cts*.rpt", "timing"),
    ],
    "route": [
        ("*route*.rpt", "timing"),
        ("*congestion*.rpt", "congestion"),
        ("*drc*.rpt", "drc"),
    ],
    "finish": [
        ("*timing*.rpt", "timing"),
        ("*power*.rpt", "power"),
        ("*area*.rpt", "utilization"),
    ],
}


class ORFSBackend(AbstractEDABackend):
    """Backend that drives OpenROAD Flow Scripts via ``make``."""

    def __init__(self, orfs_root: Path | None = None) -> None:
        self._orfs_root: Path = orfs_root or settings.orfs_root
        self._flow_dir: Path = self._orfs_root / "flow"
        self._make_jobs: int = settings.orfs_make_jobs

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "orfs"

    @property
    def version(self) -> str:
        """Try to read the OpenROAD version from the installed binary."""
        try:
            result = subprocess.run(
                ["openroad", "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            first_line = (result.stdout or result.stderr).splitlines()[0]
            return first_line.strip()
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def get_supported_stages(self) -> list[str]:
        return list(ORFS_STAGES)

    def is_available(self) -> bool:
        return self._flow_dir.is_dir()

    def run_stage(
        self,
        stage: str,
        design: DesignSpec,
        params: dict[str, Any],
    ) -> RunResult:
        params = self.validate_params(stage, params)
        run_id = str(uuid.uuid4())
        started_at = datetime.now(tz=timezone.utc)

        target = _STAGE_TARGETS[stage]
        log_dir = self._flow_dir / "logs" / design.pdk / design.name / stage
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{run_id}.log"

        report_dir = (
            self._flow_dir
            / "reports"
            / design.pdk
            / design.name
            / stage
        )

        cmd = self._build_make_cmd(target, design, params)
        logger.info("ORFS run_stage %s | cmd: %s", stage, " ".join(cmd))

        status = StageStatus.FAILED
        error_message = ""
        try:
            with log_path.open("w") as log_fh:
                proc = subprocess.run(
                    cmd,
                    cwd=str(self._flow_dir),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=7200,  # 2 h hard limit
                )
            if proc.returncode == 0:
                status = StageStatus.SUCCESS
            else:
                error_message = f"make exited with code {proc.returncode}"
        except subprocess.TimeoutExpired:
            error_message = "Stage timed out after 2 hours"
        except FileNotFoundError:
            error_message = f"'make' executable not found; check PATH"
        except Exception as exc:
            error_message = str(exc)

        finished_at = datetime.now(tz=timezone.utc)
        return RunResult(
            run_id=run_id,
            backend_name=self.name,
            design_name=design.name,
            stage=stage,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            log_path=log_path,
            report_dir=report_dir if report_dir.is_dir() else None,
            params=params,
            error_message=error_message,
        )

    def collect_reports(self, result: RunResult) -> list[ReportFile]:
        if result.report_dir is None or not result.report_dir.is_dir():
            logger.warning(
                "No report_dir for run %s (stage=%s)", result.run_id, result.stage
            )
            return []

        patterns = _REPORT_PATTERNS.get(result.stage, [("*.rpt", "generic")])
        found: dict[Path, str] = {}  # path → report_type (dedup by path)
        for glob_pat, rtype in patterns:
            for p in result.report_dir.glob(glob_pat):
                if p not in found:
                    found[p] = rtype

        return [
            ReportFile(
                path=p,
                report_type=rtype,
                stage=result.stage,
                run_id=result.run_id,
                backend_name=self.name,
            )
            for p, rtype in found.items()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_make_cmd(
        self,
        target: str,
        design: DesignSpec,
        params: dict[str, Any],
    ) -> list[str]:
        cmd = [
            "make",
            f"-j{self._make_jobs}",
            f"-C", str(self._flow_dir),
            f"DESIGN_CONFIG={design.config_path}",
            target,
        ]
        # Extra make variable overrides from params
        for key, value in params.items():
            cmd.append(f"{key}={value}")
        return cmd
