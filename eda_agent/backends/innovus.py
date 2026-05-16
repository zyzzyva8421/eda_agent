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
        # Must come AFTER _map to avoid double-matching
        ("*congestion.rpt", "innovus_congestion"),
    ],
    "prects": [
        ("*prects*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*area*.rpt", "innovus_utilization"),
        ("*congestion_map*.rpt", "innovus_congestion_map"),
        ("*congestion*.rpt", "innovus_congestion"),
    ],
    "cts": [
        ("*cts*.rpt", "innovus_timing"),
        ("*clock*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*area*.rpt", "innovus_utilization"),
        ("*congestion_map*.rpt", "innovus_congestion_map"),
        ("*congestion*.rpt", "innovus_congestion"),
    ],
    "postcts": [
        ("*postcts*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*area*.rpt", "innovus_utilization"),
        ("*congestion_map*.rpt", "innovus_congestion_map"),
        ("*congestion*.rpt", "innovus_congestion"),
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
    "postroute": [
        ("*postroute*.rpt", "innovus_timing"),
        ("*timing*.rpt", "innovus_timing"),
        ("*power*.rpt", "innovus_power"),
        ("*area*.rpt", "innovus_utilization"),
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
        ("*congestion_map*.rpt", "innovus_congestion_map"),
        ("*congestion*.rpt", "innovus_congestion"),
        ("*qor.rpt", "summary"),
    ],
}

_INNOVUS_STAGES = [
    "synth",          # typically handled by Genus; included for symmetry
    "floorplan",
    "powerplan",
    "place",
    "prects",
    "cts",
    "postcts",
    "route",
    "postroute",
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
            raise RuntimeError(
                "Innovus SSH is not configured. "
                "Set INNOVUS_SSH_HOST/INNOVUS_SSH_USER."
            )

        run_id = str(uuid.uuid4())
        started_at = datetime.now(tz=timezone.utc)

        logs_dir = Path("/tmp/eda_agent/innovus") / design.name / stage
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{run_id}.log"

        # Auto-find script if not provided
        remote_tcl = str(params.get("tcl", "")).strip()
        remote_cmd = str(params.get("command", "")).strip()
        
        # Use shared workdir
        remote_workdir = str(params.get("workdir", self._workdir)).strip()
        
        # Job-specific workdir for isolation
        job_workdir = f"{remote_workdir}/runs/{run_id}"
        
        # Get stage order for PREV_STAGE calculation
        stage_order = ["floorplan", "powerplan", "place", "prects", "cts", "postcts", "route", "postroute", "signoff"]
        try:
            stage_idx = stage_order.index(stage)
            prev_stage = stage_order[stage_idx - 1] if stage_idx > 0 else ""
        except ValueError:
            prev_stage = ""
        
        # Get local TCL scripts path
        local_scripts_dir = Path(__file__).parent / "scripts" / "innovus"
        
        # Sync local TCL scripts to remote common directory (if local scripts exist)
        if local_scripts_dir.exists():
            sync_cmd = f"mkdir -p {shlex.quote(remote_workdir)}/scripts"
            self._ssh_run(sync_cmd, timeout=30)
            # Upload each TCL script
            for tcl_file in local_scripts_dir.glob("*.tcl"):
                if tcl_file.name.startswith("agent_args"):
                    continue  # Skip agent_args templates, will be generated per-job
                if tcl_file.name == "inject_hook.tcl":
                    continue  # Will be synced separately or exists on remote
                with open(tcl_file, "r") as f:
                    tcl_content = f.read()
                # Quote content for safe shell transfer
                escaped_content = tcl_content.replace("'", "'\\''")
                upload_cmd = f"cat > {shlex.quote(remote_workdir)}/scripts/{tcl_file.name} <<'TCLEOF'\n{escaped_content}\nTCLEOF"
                self._ssh_run(upload_cmd, timeout=30)
        
        # Create job-specific directory with copied scripts and previous stage DB
        # Key insight: 
        # - First run (no prev_job_id): copy from common (remote_workdir)
        # - Iterations (has prev_job_id): copy from previous job
        prev_db_copy = ""
        if stage == "floorplan":
            # floorplan restores from initial saved design in common/FPR/saved
            saved_design = f"{remote_workdir}/FPR/saved/{design.name}.dat"
            prev_db_copy = (
                f"&& mkdir -p {shlex.quote(job_workdir)}/FPR/saved && "
                f"cp {saved_design} {shlex.quote(job_workdir)}/FPR/saved/ 2>/dev/null || true"
            )
        elif stage != "floorplan" and prev_stage:
            prev_job_id = params.get("prev_job_id", "")
            last_job_id = params.get("last_job_id", "")  # Previous stage's job ID
            
            if prev_job_id:
                # Copy from previous iteration's output
                prev_work_base = f"{remote_workdir}/runs/{prev_job_id}/FPR/work/{prev_stage}"
            elif last_job_id:
                # First run after previous stage, copy from previous stage's job output
                prev_work_base = f"{remote_workdir}/runs/{last_job_id}/FPR/work/{prev_stage}"
            else:
                # Fallback: try common directory
                prev_work_base = f"{remote_workdir}/FPR/work/{prev_stage}"
            
            prev_db_copy = (
                f"&& mkdir -p {shlex.quote(job_workdir)}/FPR/work/{prev_stage} && "
                f"cp -r {prev_work_base}/{prev_stage}.dat "
                f"{shlex.quote(job_workdir)}/FPR/work/{prev_stage}/ 2>/dev/null || true"
            )
        
        setup_cmd = (
            f"mkdir -p {shlex.quote(job_workdir)}/scripts && "
            f"mkdir -p {shlex.quote(job_workdir)}/FPR/work && "
            f"cp -r {shlex.quote(remote_workdir)}/scripts/*.tcl {shlex.quote(job_workdir)}/scripts/ 2>/dev/null || true {prev_db_copy}"
        )
        self._ssh_run(setup_cmd, timeout=60)
        
        # For default script (not custom command), inherit from previous if exists
        if not remote_cmd:
            prev_agent_args = str(params.get("prev_agent_args", "")).strip()
            
            if prev_agent_args:
                # Inherit previous injection
                self._ssh_run(
                    f"cp {shlex.quote(prev_agent_args)} {shlex.quote(job_workdir)}/scripts/agent_args_inherited.tcl",
                    timeout=10
                )
            
            agent_args_tcl = f"{job_workdir}/scripts/agent_args_{run_id}.tcl"
            if prev_agent_args:
                # Source inherited file
                self._ssh_run(
                    f'echo "source {job_workdir}/scripts/agent_args_inherited.tcl" > {shlex.quote(agent_args_tcl)}',
                    timeout=10
                )
            
            params["tcl"] = agent_args_tcl
            params["_agent_args_inherited"] = f"{job_workdir}/scripts/agent_args_inherited.tcl"
        
        # Always use job-specific workdir
        params["workdir"] = job_workdir
        
        # Default script location - use stage-specific script from job directory
        default_script = f"{job_workdir}/scripts/{stage}.tcl"
        if not remote_tcl and not remote_cmd:
            remote_tcl = default_script

        timeout_sec = int(params.get("timeout_sec", self._timeout_sec))

        if not remote_cmd:
            if not remote_tcl:
                raise ValueError("Innovus stage requires params['tcl'] or params['command'].")
            # Use job-specific workdir for execution with environment variables
            use_workdir = str(params.get("workdir", job_workdir)).strip()
            # Pass environment variables for job isolation and stage chaining
            # JOB_WORKDIR: job-specific workdir
            # PREV_STAGE: previous stage name (for restore)
            # CASE_DIR: base case directory (for initial DB restore)
            # PREV_JOB_DIR: previous job's workdir (for direct restore without copy)
            env_vars = f"JOB_WORKDIR={shlex.quote(job_workdir)}"
            if prev_stage:
                env_vars += f" PREV_STAGE={shlex.quote(prev_stage)}"
            if stage == "floorplan":
                env_vars += f" CASE_DIR={shlex.quote(remote_workdir)}"
            prev_job_id = params.get("last_job_id", "")
            if prev_job_id:
                # Pass previous job's directory for direct restore
                env_vars += f" PREV_JOB_DIR={shlex.quote(remote_workdir)}/runs/{prev_job_id}"
            remote_cmd = (
                f"cd {shlex.quote(use_workdir)} && "
                f"export {env_vars} && "
                f"{shlex.quote(self._innovus_bin)} "
                f"-no_gui -overwrite -files {shlex.quote(remote_tcl)}"
            )

        status = StageStatus.FAILED
        error_message = ""
        # report_dir is the local directory where reports will be copied to
        # Use job-specific workdir for reports
        use_workdir = str(params.get("workdir", job_workdir)).strip()
        remote_rpt_dir = str(params.get("report_dir", "")).strip() or (
            f"{use_workdir}/FPR/work/{stage}"
        )
        # Use isolated local report dir for each run to avoid pollution
        local_report_dir = Path("/tmp/eda_agent/innovus") / design.name / stage / run_id / "reports"
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
        run_id: str | None = None,
        job_workdir: str | None = None,
        prev_agent_args: str | None = None,
        stage: str = "place",
    ) -> dict[str, Any]:
        """Apply placement blockages using inject_hook mechanism.

        Generates agent_args.tcl with INJECT_PLACEDESIGN_BEFORE variable,
        which is sourced by place.tcl before placeDesign for dynamic injection.
        
        Args:
            run_id: Current run ID for job-specific file naming
            job_workdir: Job-specific workdir (e.g., {base}/runs/{run_id})
            prev_agent_args: Previous run's agent_args.tcl to inherit from
        """
        if not blockage_specs:
            raise ValueError("blockage_specs cannot be empty")
        
        base_workdir = job_workdir if job_workdir else self._workdir
        if not base_workdir:
            raise ValueError("Innovus remote workdir is not configured")
        remote_workdir = str(base_workdir).strip()
        
        # Use job-specific directory if run_id provided
        if run_id and not job_workdir:
            remote_workdir = f"{self._workdir}/runs/{run_id}"
        
        scripts_dir = f"{remote_workdir}/FPR/scripts"
        
        # Generate run_id if not provided
        if not run_id:
            run_id = str(uuid.uuid4())
        
        # Job-specific agent_args file
        agent_args_tcl = f"{scripts_dir}/agent_args_{run_id}.tcl"
        
        # Inherit from previous if provided
        inherited_cmds = []
        if prev_agent_args:
            # Read previous agent_args.tcl to extract commands
            read_prev = self._ssh_run(f"cat {prev_agent_args}", timeout=10)
            if read_prev.returncode == 0 and read_prev.stdout:
                inherited_cmds.append(f"# Inherited from previous run")
                inherited_cmds.append(f"source {shlex.quote(prev_agent_args)}")
        
        # Generate injection commands for each blockage spec
        cmds: list[str] = inherited_cmds + []
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
            reason = spec.get("reason", f"llm_blockage_{idx}")
            cmds.append(
                f'    puts "== INJECTED blockage {idx}: {reason} =="\n'
                f'    createPlaceBlockage -box {int(x1)} {int(y1)} {int(x2)} {int(y2)} -type {btype}'
            )

        # Generate agent_args.tcl with INJECT_PLACEDESIGN_BEFORE variable
        script_body = (
            f"# Auto-generated agent_args.tcl for run {run_id}\n"
            "# This file is sourced by place.tcl before inject_hook.tcl\n"
            "set ::INJECT_PLACEDESIGN_BEFORE {\n"
            + "\n".join(cmds) + "\n"
            "}\n"
        )

        write_script_cmd = (
            f"mkdir -p {shlex.quote(scripts_dir)} && "
            f"cat > {shlex.quote(agent_args_tcl)} <<'EOF'\n{script_body}EOF\n"
        )
        write_result = self._ssh_run(write_script_cmd, timeout=30)
        if write_result.returncode != 0:
            raise RuntimeError("Failed to write remote agent_args.tcl")

        return {
            "status": "success",
            "run_id": run_id,
            "workdir": remote_workdir,
            "stage": stage,
            "injection_file": agent_args_tcl,
            "injection_commands": cmds,
            "prev_agent_args": prev_agent_args,
            "mechanism": "inject_hook",
            "blockage_count": len(blockage_specs),
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
            last_reason = (
                f"attempt {attempt}/{self._connect_retries}: "
                f"host {self._host} not reachable"
            )
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
        result = self._ssh_run_once(
            "echo __eda_ssh_probe_ok__",
            timeout=self._ssh_probe_timeout_sec,
        )
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
