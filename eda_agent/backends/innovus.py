"""Cadence Innovus backend via SSH.

This backend executes Innovus on a remote host through SSH. It assumes the
remote environment already has Innovus installed and licensed.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
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

# Report filename patterns per stage (relative to the working directory)
_INNOVUS_REPORT_PATTERNS = {
    "floorplan": [
        ("*.def", "generic"),
        ("*floorplan*.rpt", "innovus_utilization"),
        ("*area*.rpt", "innovus_utilization"),
    ],
    "powerplan": [
        ("*power*.rpt", "innovus_power"),
    ],
    "place": [
        ("*place*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*area*.rpt", "innovus_utilization"),
        ("*geom*.rpt", "innovus_drc"),
        ("*drc*.rpt", "innovus_drc"),
        ("*congestion_map*.rpt", "innovus_congestion_map"),
        ("*congestion*.rpt", "innovus_congestion"),
    ],
    "cts": [
        ("*cts*.rpt", "innovus_timing"),
        ("*clock*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
    ],
    "route": [
        ("*route*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*drc*.rpt", "innovus_drc"),
        ("*geom*.rpt", "innovus_drc"),
        ("*congestion_map*.rpt", "innovus_congestion_map"),
        ("*congestion*.rpt", "innovus_congestion"),
    ],
    "signoff": [
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*area*.rpt", "innovus_utilization"),
        ("*geom*.rpt", "innovus_drc"),
        ("*qor.rpt", "summary"),
    ],
}

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
    """Cadence Innovus backend driven over SSH."""

    def __init__(self) -> None:
        self._host = settings.innovus_ssh_host
        self._user = settings.innovus_ssh_user
        self._port = settings.innovus_ssh_port
        self._password = settings.innovus_ssh_password
        self._innovus_bin = settings.innovus_bin
        self._workdir = settings.innovus_remote_workdir
        self._timeout_sec = settings.innovus_timeout_sec
        self._connect_retries = max(1, settings.innovus_connect_retries)
        self._connect_initial_backoff = max(0.1, settings.innovus_connect_initial_backoff_sec)
        self._connect_backoff_multiplier = max(1.0, settings.innovus_connect_backoff_multiplier)
        self._connect_max_backoff = max(0.1, settings.innovus_connect_max_backoff_sec)
        self._ssh_probe_timeout_sec = max(1, settings.innovus_ssh_probe_timeout_sec)

    @property
    def name(self) -> str:
        return "innovus"

    @property
    def version(self) -> str:
        if not self.is_available():
            return "unavailable"
        cmd = f"{shlex.quote(self._innovus_bin)} -version | head -n 1"
        result = self._ssh_run(cmd, timeout=20)
        if result.returncode != 0:
            return "unknown"
        return (result.stdout or "unknown").strip() or "unknown"

    def get_supported_stages(self) -> list[str]:
        return list(_INNOVUS_STAGES)

    def is_available(self) -> bool:
        if not self._host or not self._user or not self._innovus_bin:
            return False
        test_cmd = f"test -x {shlex.quote(self._innovus_bin)}"
        result = self._ssh_run(test_cmd, timeout=10)
        return result.returncode == 0

    def run_stage(
        self,
        stage: str,
        design: DesignSpec,
        params: dict[str, Any],
    ) -> RunResult:
        params = self.validate_params(stage, params)
        if not self._host or not self._user:
            raise RuntimeError("Innovus SSH is not configured. Set INNOVUS_SSH_HOST/INNOVUS_SSH_USER.")

        run_id = str(uuid.uuid4())
        started_at = datetime.now(tz=timezone.utc)

        logs_dir = Path("/tmp/eda_agent/innovus") / design.name / stage
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{run_id}.log"

        # Auto-find script if not provided
        remote_tcl = str(params.get("tcl", "")).strip()
        remote_cmd = str(params.get("command", "")).strip()
        remote_workdir = str(params.get("workdir", self._workdir)).strip()

        # Default script location on remote
        default_script_dir = f"{remote_workdir}/scripts"
        if not remote_tcl and not remote_cmd:
            # Try to use stage-specific script
            remote_tcl = f"{default_script_dir}/{stage}.tcl"

        timeout_sec = int(params.get("timeout_sec", self._timeout_sec))

        if not remote_cmd:
            if not remote_tcl:
                raise ValueError("Innovus stage requires params['tcl'] or params['command'].")
            remote_cmd = (
                f"cd {shlex.quote(remote_workdir)} && "
                f"{shlex.quote(self._innovus_bin)} -no_gui -overwrite -files {shlex.quote(remote_tcl)}"
            )

        status = StageStatus.FAILED
        error_message = ""
        # report_dir is the local directory where reports will be copied to
        remote_rpt_dir = str(params.get("report_dir", "")).strip() or f"{remote_workdir}/FPR/work/{stage}"
        local_report_dir = Path("/tmp/eda_agent/innovus") / design.name / stage / "reports"
        if local_report_dir.exists():
            shutil.rmtree(local_report_dir)
        local_report_dir.mkdir(parents=True, exist_ok=True)

        probe_ok, probe_msg = self._wait_for_connectivity()
        if not probe_ok:
            finished_at = datetime.now(tz=timezone.utc)
            return RunResult(
                run_id=run_id,
                backend_name=self.name,
                design_name=design.name,
                stage=stage,
                status=StageStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                log_path=log_path,
                report_dir=local_report_dir,
                params=params,
                error_message=probe_msg,
            )

        result = self._ssh_run(remote_cmd, timeout=timeout_sec)
        log_path.write_text((result.stdout or "") + (result.stderr or ""))
        if result.returncode == 0:
            status = StageStatus.SUCCESS
            # Copy reports from remote to local
            self._scp_copy(remote_rpt_dir, str(local_report_dir))
        else:
            error_message = f"Remote Innovus command failed with exit code {result.returncode}"

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
            report_dir=local_report_dir,
            params=params,
            error_message=error_message,
        )

    def collect_reports(self, result: RunResult) -> list[ReportFile]:
        if result.report_dir is None or not result.report_dir.is_dir():
            return []

        patterns = _INNOVUS_REPORT_PATTERNS.get(result.stage, [("*.rpt", "generic")])
        seen: set[tuple[Path, str]] = set()
        files: list[ReportFile] = []
        for glob_pat, rtype in patterns:
            for p in result.report_dir.rglob(glob_pat):
                if not p.is_file():
                    continue
                key = (p, rtype)
                if key not in seen:
                    seen.add(key)
                    files.append(
                        ReportFile(
                            path=p,
                            report_type=rtype,
                            stage=result.stage,
                            run_id=result.run_id,
                            backend_name=self.name,
                        )
                    )

        return files

    def add_blockage_to_design_state(
        self,
        *,
        design_name: str,
        blockage_specs: list[dict[str, Any]],
        workdir: str | None = None,
        stage: str = "place",
    ) -> dict[str, Any]:
        """Write and apply placement blockages to remote Innovus design state."""
        if not blockage_specs:
            raise ValueError("blockage_specs cannot be empty")
        remote_workdir = (workdir or self._workdir).strip()
        output_dir = f"{remote_workdir}/FPR/work/{stage}"
        saved_dir = f"{remote_workdir}/FPR/saved"
        blockages_tcl = f"{output_dir}/blockages.tcl"
        apply_tcl = f"{output_dir}/apply_blockages.tcl"

        cmds: list[str] = []
        for idx, spec in enumerate(blockage_specs, start=1):
            btype = str(spec.get("type", "soft")).strip().lower()
            if btype not in {"soft", "hard", "partial"}:
                raise ValueError(f"Unsupported blockage type at index {idx}: {btype}")
            try:
                x1 = float(spec["x1"])
                y1 = float(spec["y1"])
                x2 = float(spec["x2"])
                y2 = float(spec["y2"])
            except KeyError as exc:
                raise ValueError(f"Missing blockage coordinate at index {idx}: {exc}") from exc
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"Invalid blockage bbox at index {idx}: ({x1},{y1})-({x2},{y2})")
            cmds.append(
                "createPlaceBlockage -type "
                f"{shlex.quote(btype)} -box {{{x1} {y1} {x2} {y2}}}"
            )

        script_body = "\n".join(cmds) + "\n"
        quoted_blockage = shlex.quote(script_body)

        write_script_cmd = (
            f"mkdir -p {shlex.quote(output_dir)} && "
            f"cat > {shlex.quote(blockages_tcl)} <<'EOF'\n{script_body}EOF\n"
        )
        write_result = self._ssh_run(write_script_cmd, timeout=30)
        if write_result.returncode != 0:
            raise RuntimeError("Failed to write remote blockages.tcl")

        apply_body = (
            f"restoreDesign {saved_dir}/pr.inv.dat {design_name}\n"
            f"source {blockages_tcl}\n"
            f"saveDesign {saved_dir}/pr.inv.dat\n"
            "exit 0\n"
        )
        apply_cmd = (
            f"cat > {shlex.quote(apply_tcl)} <<'EOF'\n{apply_body}EOF\n"
            f"cd {shlex.quote(remote_workdir)} && "
            f"{shlex.quote(self._innovus_bin)} -no_gui -overwrite -files {shlex.quote(apply_tcl)}"
        )
        apply_result = self._ssh_run(apply_cmd, timeout=120)
        if apply_result.returncode != 0:
            raise RuntimeError("Failed to apply placement blockages in Innovus")

        return {
            "status": "success",
            "workdir": remote_workdir,
            "stage": stage,
            "blockage_file": blockages_tcl,
            "blockage_count": len(blockage_specs),
            "script_preview": quoted_blockage,
        }

    def _ssh_run(self, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess[str]:
        backoff = self._connect_initial_backoff
        last_result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(1, self._connect_retries + 1):
            result = self._ssh_run_once(remote_cmd, timeout)
            last_result = result
            if result.returncode == 0:
                return result
            if attempt >= self._connect_retries or not self._is_transient_ssh_failure(result):
                return result
            time.sleep(backoff)
            backoff = min(self._connect_max_backoff, backoff * self._connect_backoff_multiplier)

        return last_result or subprocess.CompletedProcess(
            args=["ssh", remote_cmd],
            returncode=255,
            stdout="",
            stderr="SSH failed with unknown error",
        )

    def _ssh_run_once(self, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess[str]:
        ssh_target = f"{self._user}@{self._host}"
        # sshpass requires BatchMode=no, otherwise ssh tries key auth and fails
        batch_mode = "no" if self._password else "yes"
        base_cmd: list[str] = [
            "ssh",
            "-p",
            str(self._port),
            "-o",
            f"BatchMode={batch_mode}",
            "-o",
            "StrictHostKeyChecking=no",
            ssh_target,
            remote_cmd,
        ]
        if self._password:
            base_cmd = ["sshpass", "-p", self._password] + base_cmd
        try:
            return subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=base_cmd,
                returncode=255,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\nSSH command timed out",
            )

    @staticmethod
    def _is_transient_ssh_failure(result: subprocess.CompletedProcess[str]) -> bool:
        if result.returncode == 0:
            return False
        msg = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        transient_signatures = [
            "no route to host",
            "connection timed out",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "operation timed out",
            "timed out",
            "kex_exchange_identification",
        ]
        return any(sig in msg for sig in transient_signatures)

    def _wait_for_connectivity(self) -> tuple[bool, str]:
        """Probe host reachability with ping+ssh using exponential backoff."""
        backoff = self._connect_initial_backoff
        last_reason = ""
        for attempt in range(1, self._connect_retries + 1):
            if self._probe_ping() and self._probe_ssh():
                return True, ""
            last_reason = f"attempt {attempt}/{self._connect_retries}: host {self._host} not reachable"
            if attempt < self._connect_retries:
                time.sleep(backoff)
                backoff = min(self._connect_max_backoff, backoff * self._connect_backoff_multiplier)
        return False, f"Innovus connectivity preflight failed: {last_reason}"

    def _probe_ping(self) -> bool:
        ping_cmd = ["ping", "-c", "1", "-W", "2", self._host]
        try:
            proc = subprocess.run(ping_cmd, capture_output=True, text=True, timeout=5)
            return proc.returncode == 0
        except Exception:
            return False

    def _probe_ssh(self) -> bool:
        result = self._ssh_run_once("echo __eda_ssh_probe_ok__", timeout=self._ssh_probe_timeout_sec)
        return result.returncode == 0 and "__eda_ssh_probe_ok__" in (result.stdout or "")

    def _scp_copy(self, remote_dir: str, local_dir: str) -> None:
        """Copy reports from remote Innovus working directory to local machine."""
        ssh_target = f"{self._user}@{self._host}"
        scp_cmd = [
            "scp",
            "-o",
            "StrictHostKeyChecking=no",
            "-P",
            str(self._port),
            "-r",
            f"{ssh_target}:{remote_dir}/*",
            local_dir + "/",
        ]
        if self._password:
            scp_cmd = ["sshpass", "-p", self._password] + scp_cmd
        subprocess.run(scp_cmd, capture_output=True, timeout=60)
