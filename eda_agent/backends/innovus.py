"""Cadence Innovus backend via SSH.

This backend executes Innovus on a remote host through SSH. It assumes the
remote environment already has Innovus installed and licensed.
"""

from __future__ import annotations

import os
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
    def name(self) -> str:
        return "innovus"

    @property
    def version(self) -> str:
        if not self.is_available():
            return "unavailable"
        mode = settings.innovus_execution_mode
        if mode == "local":
            cmd = f"{shlex.quote(settings.innovus_bin)} -version | head -n 1"
            result = self._local_run(cmd, timeout=20)
        else:
            cmd = f"{shlex.quote(self._innovus_bin)} -version | head -n 1"
            result = self._ssh_run(cmd, timeout=20)
        if result.returncode != 0:
            return "unknown"
        return (result.stdout or "unknown").strip() or "unknown"

    def get_supported_stages(self) -> list[str]:
        return list(_INNOVUS_STAGES)

    def is_available(self) -> bool:
        mode = settings.innovus_execution_mode
        if mode == "local":
            return Path(settings.innovus_bin).exists()
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

        mode = settings.innovus_execution_mode
        if mode == "ssh":
            if not self._host or not self._user:
                raise RuntimeError(
                    "Innovus SSH is not configured. "
                    "Set INNOVUS_SSH_HOST/INNOVUS_SSH_USER."
                )

        run_id = str(uuid.uuid4())
        params["_run_id"] = run_id
        started_at = datetime.now(tz=timezone.utc)

        logs_dir = Path("/tmp/eda_agent/innovus") / design.name / stage
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{run_id}.log"

        # ── Local / PBS / Slurm: set up workdir locally ───────────────────────
        if mode != "ssh":
            local_workdir = self._local_workdir(stage, design, params)
            Path(local_workdir).mkdir(parents=True, exist_ok=True)
            (Path(local_workdir) / "scripts").mkdir(exist_ok=True)
            (Path(local_workdir) / "FPR" / "work").mkdir(parents=True, exist_ok=True)

            backend_scripts = Path(__file__).parent / "scripts" / "innovus"
            if backend_scripts.exists():
                for tcl in backend_scripts.glob("*.tcl"):
                    if tcl.name.startswith("agent_args"):
                        continue
                    shutil.copy2(tcl, Path(local_workdir) / "scripts" / tcl.name)

            result, workdir = self._dispatch(stage, design, params)

            stdout_str = result.stdout.decode() if isinstance(result.stdout, bytes) else (result.stdout or "")
            stderr_str = result.stderr.decode() if isinstance(result.stderr, bytes) else (result.stderr or "")
            log_path.write_text(stdout_str + stderr_str)

            status = StageStatus.SUCCESS if result.returncode == 0 else StageStatus.FAILED
            error_message = "" if result.returncode == 0 else f"Innovus ({mode}) failed with exit code {result.returncode}"

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
                report_dir=Path(workdir),
                params=params,
                error_message=error_message,
            )

        # ── SSH execution path ────────────────────────────────────────────────
        remote_tcl = str(params.get("tcl", "")).strip()
        remote_cmd = str(params.get("command", "")).strip()
        remote_workdir = str(params.get("workdir", self._workdir)).strip()
        job_workdir = f"{remote_workdir}/runs/{run_id}"

        stage_order = ["floorplan", "powerplan", "place", "prects", "cts", "postcts", "route", "postroute", "signoff"]
        try:
            stage_idx = stage_order.index(stage)
            prev_stage = stage_order[stage_idx - 1] if stage_idx > 0 else ""
        except ValueError:
            prev_stage = ""

        local_scripts_dir = Path(__file__).parent / "scripts" / "innovus"
        if local_scripts_dir.exists():
            sync_cmd = f"mkdir -p {shlex.quote(remote_workdir)}/scripts"
            self._ssh_run(sync_cmd, timeout=30)
            for tcl_file in local_scripts_dir.glob("*.tcl"):
                if tcl_file.name.startswith("agent_args") or tcl_file.name == "inject_hook.tcl":
                    continue
                with open(tcl_file) as f:
                    tcl_content = f.read()
                escaped = tcl_content.replace("'", "'\\''")
                upload_cmd = f"cat > {shlex.quote(remote_workdir)}/scripts/{tcl_file.name} <<'TCLEOF'\n{escaped}\nTCLEOF"
                self._ssh_run(upload_cmd, timeout=30)

        prev_db_copy = ""
        if stage == "floorplan":
            saved_design = f"{remote_workdir}/FPR/saved/{design.name}.dat"
            prev_db_copy = (
                f"&& mkdir -p {shlex.quote(job_workdir)}/FPR/saved && "
                f"cp {saved_design} {shlex.quote(job_workdir)}/FPR/saved/ 2>/dev/null || true"
            )
        elif prev_stage:
            prev_job_id = params.get("prev_job_id", "")
            last_job_id = params.get("last_job_id", "")
            if prev_job_id:
                prev_work_base = f"{remote_workdir}/runs/{prev_job_id}/FPR/work/{prev_stage}"
            elif last_job_id:
                prev_work_base = f"{remote_workdir}/runs/{last_job_id}/FPR/work/{prev_stage}"
            else:
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

        if not remote_cmd:
            prev_agent_args = str(params.get("prev_agent_args", "")).strip()
            if prev_agent_args:
                if "/scripts/agent_args_" in prev_agent_args:
                    prev_scripts_dir = prev_agent_args.replace("/scripts/agent_args_", "/scripts/").rsplit("/", 1)[0]
                elif "/scripts/agent_args.tcl" in prev_agent_args:
                    prev_scripts_dir = prev_agent_args.replace("/scripts/agent_args.tcl", "/scripts")
                else:
                    prev_scripts_dir = None

                if prev_scripts_dir:
                    self._ssh_run(
                        f"cp {shlex.quote(prev_scripts_dir)}/agent_args_*.tcl {shlex.quote(job_workdir)}/scripts/ 2>/dev/null || true",
                        timeout=10,
                    )
                    self._ssh_run(
                        f"cp {shlex.quote(prev_scripts_dir)}/agent_args.tcl {shlex.quote(job_workdir)}/scripts/ 2>/dev/null || true",
                        timeout=10,
                    )

            agent_args_tcl = f"{job_workdir}/scripts/agent_args_{run_id}.tcl"
            if prev_agent_args:
                inherited_src = prev_agent_args.replace("/scripts/agent_args.tcl", "/scripts/agent_args_*.tcl").rsplit("/", 1)[0]
                create_inherited = (
                    f'prev_scripts=$(ls {inherited_src}/agent_args_*.tcl 2>/dev/null | tail -1) && '
                    f'if [ -n "$prev_scripts" ]; then '
                    f'echo "source $prev_scripts" > {job_workdir}/scripts/agent_args_inherited.tcl; '
                    f'else echo "# no previous agent_args" > {job_workdir}/scripts/agent_args_inherited.tcl; fi'
                )
                self._ssh_run(create_inherited, timeout=10)
                self._ssh_run(
                    f'echo "source {job_workdir}/scripts/agent_args_inherited.tcl" > {shlex.quote(agent_args_tcl)}',
                    timeout=10,
                )
            params["tcl"] = agent_args_tcl
            params["_agent_args_inherited"] = f"{job_workdir}/scripts/agent_args_inherited.tcl"

        params["workdir"] = job_workdir

        default_script = f"{job_workdir}/scripts/{stage}.tcl"
        if not remote_tcl and not remote_cmd:
            remote_tcl = default_script

        if not remote_cmd:
            if not remote_tcl:
                raise ValueError("Innovus stage requires params['tcl'] or params['command'].")
            use_workdir = str(params.get("workdir", job_workdir)).strip()
            env_vars = f"JOB_WORKDIR={shlex.quote(job_workdir)}"
            if prev_stage:
                env_vars += f" PREV_STAGE={shlex.quote(prev_stage)}"
            if stage == "floorplan":
                env_vars += f" CASE_DIR={shlex.quote(remote_workdir)}"
            prev_job_id = params.get("last_job_id", "")
            if prev_job_id:
                env_vars += f" PREV_JOB_DIR={shlex.quote(remote_workdir)}/runs/{prev_job_id}"
            remote_cmd = (
                f"cd {shlex.quote(use_workdir)} && "
                f"export {env_vars} && "
                f"{shlex.quote(self._innovus_bin)} "
                f"-no_gui -overwrite -files {shlex.quote(remote_tcl)}"
            )

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
                report_dir=Path("/tmp"),
                params=params,
                error_message=probe_msg,
            )

        local_report_dir = Path("/tmp/eda_agent/innovus") / design.name / stage / run_id / "reports"
        if local_report_dir.exists():
            shutil.rmtree(local_report_dir)
        local_report_dir.mkdir(parents=True, exist_ok=True)

        remote_rpt_dir = str(params.get("report_dir", "")).strip() or f"{job_workdir}/FPR/work/{stage}"
        result = self._ssh_run(remote_cmd, timeout=int(params.get("timeout_sec", self._timeout_sec)))
        stdout_str = result.stdout.decode() if isinstance(result.stdout, bytes) else (result.stdout or "")
        stderr_str = result.stderr.decode() if isinstance(result.stderr, bytes) else (result.stderr or "")
        log_path.write_text(stdout_str + stderr_str)
        status = StageStatus.SUCCESS if result.returncode == 0 else StageStatus.FAILED
        if result.returncode == 0:
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
            error_message=error_message if result.returncode != 0 else "",
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
        
        # Use job-specific scripts dir (consistent with run_stage)
        scripts_dir = f"{remote_workdir}/scripts"
        
        # Generate run_id if not provided
        if not run_id:
            run_id = str(uuid.uuid4())
        
        # Job-specific agent_args file
        agent_args_tcl = f"{scripts_dir}/agent_args_{run_id}.tcl"
        
        # Inherit from previous if provided - extract actual commands
        inherited_blockages: list[str] = []  # List of individual blockage commands from previous run
        inherited_cmds: list[str] = []
        prev_blockage_count = 0
        if prev_agent_args:
            # Read previous agent_args.tcl to extract INJECT_PLACEDESIGN_BEFORE content
            read_prev = self._ssh_run(f"cat {prev_agent_args}", timeout=10)
            if read_prev.returncode == 0 and read_prev.stdout:
                prev_content = read_prev.stdout
                # Extract the content between { and } in set ::INJECT_PLACEDESIGN_BEFORE { ... }
                import re
                match = re.search(
                    r"set ::INJECT_PLACEDESIGN_BEFORE \{(.*?)\}",
                    prev_content,
                    re.DOTALL
                )
                if match:
                    inherited_blockages.append(match.group(1).strip())
                    # Count inherited blockages by counting createPlaceBlockage calls
                    prev_blockage_count = match.group(1).count("createPlaceBlockage")
        
        # Generate injection commands for each blockage spec
        all_cmds = inherited_blockages + []
        for idx, spec in enumerate(blockage_specs, start=prev_blockage_count + 1):
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
            all_cmds.append(
                f'    puts "== INJECTED blockage {idx}: {reason} =="\n'
                f'    createPlaceBlockage -box {int(x1)} {int(y1)} {int(x2)} {int(y2)} -type {btype}'
            )

        # Generate agent_args.tcl with all cumulative INJECT_PLACEDESIGN_BEFORE content
        script_body = (
            f"# Auto-generated agent_args.tcl for run {run_id}\n"
            "# This file is sourced by place.tcl before inject_hook.tcl\n"
            "# Contains cumulative blockages from all previous runs\n"
            "set ::INJECT_PLACEDESIGN_BEFORE {\n"
            + "\n".join(all_cmds) + "\n"
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
            "injection_commands": all_cmds,
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

    # ── Local execution ─────────────────────────────────────────────────────────

    def _local_run(self, cmd: str, timeout: int) -> subprocess.CompletedProcess[str]:
        """Run *cmd* directly on the local machine (no SSH)."""
        try:
            return subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=[cmd],
                returncode=255,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\nLocal command timed out",
            )

    def _wait_local_innovus(
        self, job_id: str, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        """Wait for a locally-launched Innovus process to complete.

        For local mode this is a no-op because subprocess.run blocks.
        For PBS/Slurm modes this polls the queue until the job finishes.
        """
        mode = settings.innovus_execution_mode
        if mode == "pbs":
            return self._wait_pbs_job(job_id, timeout)
        if mode == "slurm":
            return self._wait_slurm_job(job_id, timeout)
        # local: no-op, caller already waited
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    # ── PBS/Torque job submission ───────────────────────────────────────────────

    def _pbs_submit(self, script_path: str) -> tuple[str, str]:
        """Submit *script_path* to PBS/Torque (qsub).

        Returns (job_id, queue_name).
        Raises RuntimeError on failure.
        """
        qsub_cmd = ["qsub"]
        if settings.innovus_scheduler_queue:
            qsub_cmd += ["-q", settings.innovus_scheduler_queue]
        if settings.innovus_scheduler_account:
            qsub_cmd += ["-A", settings.innovus_scheduler_account]
        if settings.innovus_scheduler_extra:
            qsub_cmd += settings.innovus_scheduler_extra.split()
        qsub_cmd.append(script_path)

        result = subprocess.run(
            qsub_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"qsub failed: {result.stderr.strip()}")
        # PBS outputs "job_id.hostname\n"
        job_id = result.stdout.strip().split("\n")[0].split(".")[0]
        return job_id, settings.innovus_scheduler_queue or "default"

    def _wait_pbs_job(self, job_id: str, timeout: int) -> subprocess.CompletedProcess[str]:
        """Poll PBS job status until completion."""
        start = time.monotonic()
        while True:
            check = subprocess.run(
                ["qstat", job_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if check.returncode != 0:
                # Job no longer listed – finished (success or failure)
                break
            if time.monotonic() - start > timeout:
                subprocess.run(["qdel", job_id], capture_output=True, timeout=10)
                return subprocess.CompletedProcess(
                    args=["qdel", job_id],
                    returncode=255,
                    stdout="",
                    stderr="PBS job timed out",
                )
            time.sleep(15)
        # qstat returned non-zero → job is gone; get exit code via qacct
        acct = subprocess.run(
            ["qacct", "-j", job_id],
            capture_output=True,
            text=True,
            timeout=20,
        )
        exit_code = 0
        if acct.returncode == 0:
            for line in acct.stdout.splitlines():
                if line.startswith("exit_status"):
                    exit_code = int(line.split()[1])
        return subprocess.CompletedProcess(
            args=["qsub", job_id],
            returncode=exit_code,
            stdout="",
            stderr="",
        )

    # ── Slurm job submission ───────────────────────────────────────────────────

    def _slurm_submit(self, script_path: str) -> tuple[str, str]:
        """Submit *script_path* to Slurm (sbatch).

        Returns (job_id, partition_name).
        Raises RuntimeError on failure.
        """
        sbatch_cmd = ["sbatch"]
        if settings.innovus_scheduler_queue:
            sbatch_cmd += ["--partition", settings.innovus_scheduler_queue]
        if settings.innovus_scheduler_account:
            sbatch_cmd += ["--account", settings.innovus_scheduler_account]
        if settings.innovus_scheduler_extra:
            sbatch_cmd += settings.innovus_scheduler_extra.split()
        sbatch_cmd.append(script_path)

        result = subprocess.run(
            sbatch_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"sbatch failed: {result.stderr.strip()}")
        # sbatch outputs "Submitted batch job 12345\n"
        job_id = result.stdout.strip().split()[-1]
        return job_id, settings.innovus_scheduler_queue or "default"

    def _wait_slurm_job(self, job_id: str, timeout: int) -> subprocess.CompletedProcess[str]:
        """Poll Slurm job status until completion."""
        start = time.monotonic()
        while True:
            check = subprocess.run(
                ["squeue", "-j", job_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if check.returncode != 0 or job_id not in check.stdout:
                # Job no longer in queue – finished
                break
            if time.monotonic() - start > timeout:
                subprocess.run(["scancel", job_id], capture_output=True, timeout=10)
                return subprocess.CompletedProcess(
                    args=["scancel", job_id],
                    returncode=255,
                    stdout="",
                    stderr="Slurm job timed out",
                )
            time.sleep(15)
        # Job finished; get exit code from sacct
        acct = subprocess.run(
            ["sacct", "-j", job_id, "--format=ExitCode", "-n"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        exit_code = 0
        if acct.returncode == 0 and acct.stdout.strip():
            # First line is the job step, format: "0:0"
            parts = acct.stdout.strip().split(":")
            if len(parts) >= 2:
                exit_code = int(parts[1])
        return subprocess.CompletedProcess(
            args=["sbatch", job_id],
            returncode=exit_code,
            stdout="",
            stderr="",
        )

    # ── Execution-mode dispatcher ──────────────────────────────────────────────

    def _dispatch(
        self, stage: str, design: DesignSpec, params: dict[str, Any]
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        """Run the Innovus stage using the configured execution mode.

        Returns (result, workdir).  workdir is the directory where reports live.
        """
        mode = settings.innovus_execution_mode
        if mode == "local":
            return self._run_local(stage, design, params), self._local_workdir(stage, design, params)
        if mode == "pbs":
            return self._run_scheduler(stage, design, params, "pbs")
        if mode == "slurm":
            return self._run_scheduler(stage, design, params, "slurm")
        # Default: SSH
        return self._run_ssh(stage, design, params)

    def _local_workdir(self, stage: str, design: DesignSpec, params: dict[str, Any]) -> str:
        """Compute the local working directory for a run."""
        base = settings.innovus_local_workdir / design.name
        run_id = params.get("_run_id", str(uuid.uuid4()))
        return str(base / stage / run_id)

    def _build_innovus_cmd(
        self, stage: str, design: DesignSpec, params: dict[str, Any], *, workdir: str
    ) -> str:
        """Build the raw Innovus Tcl-launcher command (without SSH wrapper)."""
        remote_tcl = str(params.get("tcl", "")).strip()
        remote_cmd = str(params.get("command", "")).strip()

        stage_order = ["floorplan", "powerplan", "place", "prects", "cts", "postcts", "route", "postroute", "signoff"]
        try:
            stage_idx = stage_order.index(stage)
            prev_stage = stage_order[stage_idx - 1] if stage_idx > 0 else ""
        except ValueError:
            prev_stage = ""

        # agent_args.tcl in local mode lives under <workdir>/scripts/
        if not remote_tcl and not remote_cmd:
            remote_tcl = f"{workdir}/scripts/{stage}.tcl"

        timeout_sec = int(params.get("timeout_sec", settings.innovus_timeout_sec))

        if remote_cmd:
            return remote_cmd

        if not remote_tcl:
            raise ValueError("Innovus stage requires params['tcl'] or params['command']")

        env_vars = f"JOB_WORKDIR={shlex.quote(workdir)}"
        if prev_stage:
            env_vars += f" PREV_STAGE={shlex.quote(prev_stage)}"
        prev_job_id = params.get("last_job_id", "")
        if prev_job_id:
            env_vars += f" PREV_JOB_DIR={shlex.quote(str(settings.innovus_local_workdir / design.name / prev_job_id))}"

        return (
            f"cd {shlex.quote(workdir)} && "
            f"export {env_vars} && "
            f"{shlex.quote(settings.innovus_bin)} "
            f"-no_gui -overwrite -files {shlex.quote(remote_tcl)}"
        )

    def _run_local(self, stage: str, design: DesignSpec, params: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        """Execute Innovus locally (no SSH)."""
        run_id = params.get("_run_id", str(uuid.uuid4()))
        workdir = self._local_workdir(stage, design, params)

        # Create workdir tree
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scripts").mkdir(exist_ok=True)
        (Path(workdir) / "FPR" / "work").mkdir(parents=True, exist_ok=True)

        # Copy TCL scripts from the backend's scripts/ directory
        backend_scripts = Path(__file__).parent / "scripts" / "innovus"
        if backend_scripts.exists():
            for tcl in backend_scripts.glob("*.tcl"):
                if tcl.name not in ("agent_args_template.tcl",):
                    shutil.copy2(tcl, Path(workdir) / "scripts" / tcl.name)

        cmd = self._build_innovus_cmd(stage, design, params, workdir=workdir)
        timeout_sec = int(params.get("timeout_sec", settings.innovus_timeout_sec))
        return self._local_run(cmd, timeout=timeout_sec)

    def _run_ssh(self, stage: str, design: DesignSpec, params: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        """Execute Innovus via SSH (legacy path)."""
        remote_tcl = str(params.get("tcl", "")).strip()
        remote_cmd = str(params.get("command", "")).strip()
        use_workdir = str(params.get("workdir", self._workdir)).strip()

        stage_order = ["floorplan", "powerplan", "place", "prects", "cts", "postcts", "route", "postroute", "signoff"]
        try:
            stage_idx = stage_order.index(stage)
            prev_stage = stage_order[stage_idx - 1] if stage_idx > 0 else ""
        except ValueError:
            prev_stage = ""

        if not remote_cmd:
            if not remote_tcl:
                raise ValueError("Innovus stage requires params['tcl'] or params['command']")
            timeout_sec = int(params.get("timeout_sec", self._timeout_sec))
            env_vars = f"JOB_WORKDIR={shlex.quote(use_workdir)}"
            if prev_stage:
                env_vars += f" PREV_STAGE={shlex.quote(prev_stage)}"
            remote_cmd = (
                f"cd {shlex.quote(use_workdir)} && "
                f"export {env_vars} && "
                f"{shlex.quote(self._innovus_bin)} "
                f"-no_gui -overwrite -files {shlex.quote(remote_tcl)}"
            )

        timeout_sec = int(params.get("timeout_sec", self._timeout_sec))
        return self._ssh_run(remote_cmd, timeout=timeout_sec)

    def _run_scheduler(
        self, stage: str, design: DesignSpec, params: dict[str, Any], scheduler: str
    ) -> subprocess.CompletedProcess[str]:
        """Execute Innovus via PBS or Slurm job submission.

        Generates a wrapper shell script, submits it, then polls until done.
        """
        run_id = params.get("_run_id", str(uuid.uuid4()))
        workdir = self._local_workdir(stage, design, params)
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scripts").mkdir(exist_ok=True)

        cmd = self._build_innovus_cmd(stage, design, params, workdir=workdir)

        # Write wrapper script
        if scheduler == "pbs":
            script = self._pbs_wrapper_script(workdir, cmd)
        else:
            script = self._slurm_wrapper_script(workdir, cmd)

        script_path = Path(workdir) / f"submit.{scheduler}"
        script_path.write_text(script, encoding="utf-8")
        os.chmod(script_path, 0o755)

        if scheduler == "pbs":
            job_id, _ = self._pbs_submit(str(script_path))
        else:
            job_id, _ = self._slurm_submit(str(script_path))

        timeout_sec = int(params.get("timeout_sec", settings.innovus_timeout_sec))
        # _wait_<scheduler>_job polls until the job completes
        return self._wait_local_innovus(job_id, timeout=timeout_sec)

    def _pbs_wrapper_script(self, workdir: str, cmd: str) -> str:
        q = settings.innovus_scheduler_queue or "default"
        a = settings.innovus_scheduler_account or ""
        extra = f"#PBS -A {a}" if a else ""
        lines = [
            "#!/bin/bash",
            f"#PBS -N eda_innovus",
            f"#PBS -q {q}",
            extra,
            f"#PBS -o {workdir}/pbs.stdout.txt",
            f"#PBS -e {workdir}/pbs.stderr.txt",
            "",
            f"cd {workdir}",
            cmd,
        ]
        return "\n".join(lines)

    def _slurm_wrapper_script(self, workdir: str, cmd: str) -> str:
        p = settings.innovus_scheduler_queue or ""
        a = settings.innovus_scheduler_account or ""
        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name=eda_innovus",
            f"#SBATCH --partition={p}" if p else "",
            f"#SBATCH --account={a}" if a else "",
            f"#SBATCH --output={workdir}/slurm_%j.out",
            f"#SBATCH --error={workdir}/slurm_%j.err",
            "",
            f"cd {workdir}",
            cmd,
        ]
        return "\n".join(lines)
