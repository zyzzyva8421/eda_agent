#!/usr/bin/env python3
"""Run a real LLM-driven parameter optimization trial on ORFS place->finish flow.

Workflow:
1) Clean stages place/cts/route/finish and run baseline finish
2) Parse baseline timing summary from 6_finish.rpt
3) Ask MiniMax for place-stage parameters (PLACE_DENSITY, CELL_PAD_IN_SITES)
4) Clean stages again and run trial finish with suggested params
5) Parse trial timing summary and compare improvement

This script is intended for manual execution from repo root.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eda_agent.parsers.timing import TimingParser


def _load_dotenv(dotenv_path: Path) -> None:
    """Load .env key/value pairs into process environment if not already set."""
    if not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        value = os.path.expandvars(value)
        os.environ.setdefault(key, value)


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from potentially noisy reasoning-model output."""
    if not text:
        return None

    # Remove complete think blocks if present.
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)

    start = text.find("{")
    if start < 0:
        return None

    candidate = text[start:]
    # Progressive trim fallback for truncated output.
    for end in range(len(candidate), 1, -1):
        snippet = candidate[:end]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


def _run_cmd(cmd: list[str], cwd: Path) -> None:
    print(f"\n[CMD] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit={proc.returncode}): {' '.join(cmd)}")


def _run_orfs_finish(
    flow_dir: Path,
    design_config: Path,
    extra_make_vars: dict[str, str] | None = None,
    jobs: int = 4,
) -> None:
    clean_cmd = [
        "make",
        f"-j{jobs}",
        "-C",
        str(flow_dir),
        f"DESIGN_CONFIG={design_config}",
        "clean_place",
        "clean_cts",
        "clean_route",
        "clean_finish",
    ]
    _run_cmd(clean_cmd, cwd=flow_dir)

    finish_cmd = [
        "make",
        f"-j{jobs}",
        "-C",
        str(flow_dir),
        f"DESIGN_CONFIG={design_config}",
        "finish",
    ]
    for k, v in (extra_make_vars or {}).items():
        finish_cmd.append(f"{k}={v}")
    _run_cmd(finish_cmd, cwd=flow_dir)


def _parse_timing_summary(rpt_path: Path) -> dict[str, float | int]:
    if not rpt_path.is_file():
        raise FileNotFoundError(f"Timing report not found: {rpt_path}")

    records = TimingParser().parse_file(rpt_path)
    summary = next((r for r in records if r.get("kind") == "summary"), None)
    if not summary:
        raise RuntimeError(f"No summary record parsed from: {rpt_path}")

    return {
        "wns_ns": float(summary.get("wns_ns", 0.0)),
        "tns_ns": float(summary.get("tns_ns", 0.0)),
        "setup_violations": int(summary.get("setup_violations", 0)),
        "hold_violations": int(summary.get("hold_violations", 0)),
    }


def _request_llm_place_params(
    baseline: dict[str, float | int],
    minimax_base_url: str,
    minimax_api_key: str,
    minimax_model: str,
    minimax_group_id: str | None,
) -> dict[str, str]:
    prompt = (
        "You are an EDA physical design expert. "
        "Given baseline finish timing metrics, suggest conservative place-stage "
        "make-variable overrides to improve final timing after full rerun.\n"
        "Return ONLY a raw JSON object (no markdown, no think tags).\n"
        "Schema:\n"
        "{\n"
        "  \"diagnosis\": string,\n"
        "  \"suggested_params\": {\n"
        "    \"PLACE_DENSITY\": string,\n"
        "    \"CELL_PAD_IN_SITES\": string\n"
        "  }\n"
        "}\n"
        f"Baseline finish metrics: {json.dumps(baseline)}\n"
        "Constraints: PLACE_DENSITY in [0.55, 0.68], CELL_PAD_IN_SITES in [0, 4]."
    )

    payload = {
        "model": minimax_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert EDA assistant. "
                    "Reply with raw JSON only, no markdown fences, no <think> tags."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }

    headers = {
        "Authorization": f"Bearer {minimax_api_key}",
        "Content-Type": "application/json",
    }
    if minimax_group_id:
        headers["X-Group-Id"] = minimax_group_id

    url = f"{minimax_base_url.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    print("\n[LLM raw output]\n" + str(content)[:1200])

    parsed = _extract_first_json_object(content)
    params: dict[str, str] = {}

    if parsed and isinstance(parsed.get("suggested_params"), dict):
        for k, v in parsed["suggested_params"].items():
            if k in {"PLACE_DENSITY", "CELL_PAD_IN_SITES"}:
                params[k] = str(v)

    # Regex fallback for reasoning/truncated outputs.
    if "PLACE_DENSITY" not in params:
        m = re.search(r"PLACE_DENSITY[^\d]*(0\.\d+)", content)
        params["PLACE_DENSITY"] = m.group(1) if m else "0.60"

    if "CELL_PAD_IN_SITES" not in params:
        m = re.search(r"CELL_PAD_IN_SITES[^\d]*(\d+)", content)
        if m:
            params["CELL_PAD_IN_SITES"] = m.group(1)

    # Clamp to safe ranges.
    try:
        pd = float(params["PLACE_DENSITY"])
    except Exception:
        pd = 0.60
    pd = max(0.55, min(0.68, pd))
    params["PLACE_DENSITY"] = f"{pd:.2f}"

    if "CELL_PAD_IN_SITES" in params:
        try:
            cps = int(float(params["CELL_PAD_IN_SITES"]))
            cps = max(0, min(4, cps))
            params["CELL_PAD_IN_SITES"] = str(cps)
        except Exception:
            params.pop("CELL_PAD_IN_SITES", None)

    return params


def _compare(baseline: dict[str, float | int], trial: dict[str, float | int]) -> tuple[bool, dict[str, float | int]]:
    delta_wns = float(trial["wns_ns"]) - float(baseline["wns_ns"])
    delta_tns = float(trial["tns_ns"]) - float(baseline["tns_ns"])
    delta_setup = int(baseline["setup_violations"]) - int(trial["setup_violations"])

    improved = (delta_wns > 0.0) or (delta_tns > 0.0) or (delta_setup > 0)
    deltas: dict[str, float | int] = {
        "delta_wns_ns": round(delta_wns, 3),
        "delta_tns_ns": round(delta_tns, 3),
        "delta_setup_violations": delta_setup,
    }
    return improved, deltas


def main() -> int:
    _load_dotenv(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="LLM-guided ORFS place-stage timing improvement trial")
    parser.add_argument("--design", default=os.getenv("EDA_REAL_DESIGN_NAME", "aes"), help="Design name")
    parser.add_argument("--pdk", default=os.getenv("EDA_REAL_PDK", "sky130hd"), help="PDK name")
    parser.add_argument(
        "--orfs-root",
        default=os.getenv("ORFS_ROOT", str(Path.home() / "OpenROAD-flow-scripts")),
        help="ORFS root directory",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=int(os.getenv("ORFS_MAKE_JOBS", "4")),
        help="make -j jobs",
    )
    parser.add_argument(
        "--design-config",
        default=os.getenv("EDA_REAL_DESIGN_CONFIG"),
        help="Optional explicit config.mk path",
    )
    args = parser.parse_args()

    minimax_api_key = os.getenv("MINIMAX_API_KEY")
    minimax_base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
    minimax_model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")
    minimax_group_id = os.getenv("MINIMAX_GROUP_ID") or None

    if not minimax_api_key:
        print("ERROR: MINIMAX_API_KEY is not set.", file=sys.stderr)
        return 2

    if not args.orfs_root:
        print("ERROR: ORFS_ROOT is not set and --orfs-root not provided.", file=sys.stderr)
        return 2

    orfs_root = Path(os.path.expandvars(args.orfs_root)).expanduser().resolve()
    flow_dir = orfs_root / "flow"
    if not flow_dir.is_dir():
        print(f"ERROR: flow directory not found: {flow_dir}", file=sys.stderr)
        return 2

    if args.design_config:
        design_config = Path(args.design_config).expanduser().resolve()
    else:
        design_config = flow_dir / "designs" / args.pdk / args.design / "config.mk"

    if not design_config.is_file():
        design_root = flow_dir / "designs"
        available_pdks = []
        if design_root.is_dir():
            available_pdks = sorted(p.name for p in design_root.iterdir() if p.is_dir())
        print(f"ERROR: design config not found: {design_config}", file=sys.stderr)
        if available_pdks:
            print(
                f"Hint: available PDK folders under {design_root}: {', '.join(available_pdks)}",
                file=sys.stderr,
            )
            pdk_dir = design_root / args.pdk
            if pdk_dir.is_dir():
                candidates = sorted(p.name for p in pdk_dir.iterdir() if p.is_dir())
                if candidates:
                    print(
                        f"Hint: available designs under {pdk_dir}: {', '.join(candidates)}",
                        file=sys.stderr,
                    )
        return 2

    report_path = flow_dir / "reports" / args.pdk / args.design / "base" / "6_finish.rpt"

    print("=" * 80)
    print("[1/5] Baseline run: clean place->finish and run finish")
    _run_orfs_finish(flow_dir, design_config, extra_make_vars=None, jobs=args.jobs)

    print("\n[2/5] Parse baseline timing from 6_finish.rpt")
    baseline = _parse_timing_summary(report_path)
    print(json.dumps({"baseline": baseline}, indent=2))

    print("\n[3/5] Ask LLM for place-stage params")
    llm_params = _request_llm_place_params(
        baseline=baseline,
        minimax_base_url=minimax_base_url,
        minimax_api_key=minimax_api_key,
        minimax_model=minimax_model,
        minimax_group_id=minimax_group_id,
    )
    print(json.dumps({"llm_params": llm_params}, indent=2))

    print("\n[4/5] Trial run: clean place->finish and run with LLM params")
    _run_orfs_finish(flow_dir, design_config, extra_make_vars=llm_params, jobs=args.jobs)

    print("\n[5/5] Parse trial timing and compare")
    trial = _parse_timing_summary(report_path)
    improved, deltas = _compare(baseline, trial)

    result = {
        "design": args.design,
        "pdk": args.pdk,
        "baseline": baseline,
        "llm_params": llm_params,
        "trial": trial,
        "delta": deltas,
        "improved": improved,
    }
    print(json.dumps(result, indent=2))
    print("=" * 80)

    if improved:
        print("RESULT: IMPROVED (at least one of WNS/TNS/setup got better)")
        return 0

    print("RESULT: NOT IMPROVED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
