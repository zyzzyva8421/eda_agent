from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


def _read_meminfo_kb() -> dict[str, int]:
    data: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                data[parts[0].rstrip(":")] = int(parts[1])
    return data


def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def _ensure_swap_file(swap_file: Path, size_gb: int) -> bool:
    size_bytes = size_gb * 1024 * 1024 * 1024
    swap_file.parent.mkdir(parents=True, exist_ok=True)

    create_cmd = [
        "bash",
        "-lc",
        f"fallocate -l {size_bytes} {swap_file} || dd if=/dev/zero of={swap_file} bs=1M count={size_gb * 1024}",
    ]
    setup_cmds = [
        ["chmod", "600", str(swap_file)],
        ["mkswap", str(swap_file)],
        ["swapon", str(swap_file)],
    ]

    candidates: list[list[str]] = [create_cmd]
    candidates.extend(setup_cmds)

    if os.geteuid() == 0:
        prefix: list[str] = []
    elif shutil.which("sudo"):
        prefix = ["sudo", "-n"]
    else:
        return False

    for cmd in candidates:
        run_cmd = prefix + cmd
        result = _run_cmd(run_cmd)
        if result.returncode != 0:
            return False
    return True


def ensure_vm_test_resources(
    min_mem_available_gb: int = 8,
    min_swap_total_gb: int = 8,
    swap_file: str = "/tmp/eda_agent_vm.swap",
) -> None:
    """Ensure host has enough memory/swap headroom before heavy VM testcase runs."""
    if platform.system().lower() != "linux":
        return

    mem = _read_meminfo_kb()
    mem_avail_gb = mem.get("MemAvailable", 0) / (1024 * 1024)
    swap_total_gb = mem.get("SwapTotal", 0) / (1024 * 1024)

    need_more_swap = mem_avail_gb < float(min_mem_available_gb) and swap_total_gb < float(min_swap_total_gb)
    if not need_more_swap:
        return

    ok = _ensure_swap_file(Path(swap_file), min_swap_total_gb)
    if not ok:
        raise RuntimeError(
            "Insufficient memory headroom and failed to provision swap. "
            "Please create swap manually (or run with sudo) before VM real-case tests."
        )

    mem_after = _read_meminfo_kb()
    swap_after_gb = mem_after.get("SwapTotal", 0) / (1024 * 1024)
    if swap_after_gb < float(min_swap_total_gb):
        raise RuntimeError(
            f"Swap setup did not reach target: have {swap_after_gb:.1f} GB, "
            f"need >= {min_swap_total_gb} GB."
        )
