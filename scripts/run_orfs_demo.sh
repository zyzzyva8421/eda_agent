#!/usr/bin/env bash
# run_orfs_demo.sh – Run ORFS aes demo, parse & ingest ALL QoR metrics
#
# Usage:
#   bash scripts/run_orfs_demo.sh [ORFS_ROOT] [PDK] [DESIGN]
#   RUN_FLOW=true bash scripts/run_orfs_demo.sh   # to re-run the flow
#
# Defaults:
#   ORFS_ROOT = $HOME/OpenROAD-flow-scripts
#   PDK       = sky130hd
#   DESIGN    = aes

set -euo pipefail

ORFS_ROOT="${1:-${ORFS_ROOT:-$HOME/OpenROAD-flow-scripts}}"
PDK="${2:-sky130hd}"
DESIGN="${3:-aes}"
FLOW_DIR="${ORFS_ROOT}/flow"
DESIGN_CONFIG="${FLOW_DIR}/designs/${PDK}/${DESIGN}/config.mk"
MAKE_JOBS="${ORFS_MAKE_JOBS:-4}"

echo "============================================================"
echo "  EDA Agent – ORFS full QoR ingestion"
echo "  ORFS_ROOT : ${ORFS_ROOT}"
echo "  PDK       : ${PDK}"
echo "  DESIGN    : ${DESIGN}"
echo "============================================================"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [[ ! -d "${FLOW_DIR}" ]]; then
  echo "ERROR: ORFS flow directory not found: ${FLOW_DIR}"
  exit 1
fi
if [[ ! -f "${DESIGN_CONFIG}" ]]; then
  echo "ERROR: Design config not found: ${DESIGN_CONFIG}"
  exit 1
fi

# ── Migrations ────────────────────────────────────────────────────────────────
echo ""
echo ">>> Applying database migrations …"
PATH="/home/aliu/ORAssistant/backend/.venv/bin:$PATH" alembic upgrade head

# ── Run ORFS flow (only if requested) ────────────────────────────────────────
if [[ "${RUN_FLOW:-false}" == "true" ]]; then
  run_stage() {
    local STAGE="$1"
    echo ""
    echo ">>> Running stage: ${STAGE}"
    make -j"${MAKE_JOBS}" \
      -C "${FLOW_DIR}" \
      "DESIGN_CONFIG=${DESIGN_CONFIG}" \
      "${STAGE}"
    echo "    Stage ${STAGE} complete."
  }
  run_stage synth
  run_stage floorplan
  run_stage place
  run_stage cts
  run_stage route
  run_stage finish
else
  echo ""
  echo ">>> Skipping flow run (set RUN_FLOW=true to re-run)"
fi

# ── Ingest QoR reports for each stage ────────────────────────────────────────
echo ""
echo ">>> Ingesting QoR reports into PostgreSQL …"
PATH="/home/aliu/ORAssistant/backend/.venv/bin:$PATH" python - <<PYEOF
import sys, uuid, datetime, re, logging
from pathlib import Path
from eda_agent.backends.orfs import ORFSBackend
from eda_agent.backends.base import DesignSpec, StageStatus, RunResult
from eda_agent.agent.tools import _upsert_run, _ingest_records
from eda_agent.parsers import get_parser

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

orfs_root = Path("${ORFS_ROOT}")
pdk       = "${PDK}"
design_nm = "${DESIGN}"
config_p  = Path("${DESIGN_CONFIG}")
report_dir = orfs_root / "flow" / "reports" / pdk / design_nm / "base"
log_dir    = orfs_root / "flow" / "logs" / pdk / design_nm / "base"

# ─── area/utilization from log files ──────────────────────────────────────────
_LOG_AREA = re.compile(r"Design area\s*[\d,]+\s*([\d.]+)\s*um.?2", re.IGNORECASE)
_LOG_UTIL = re.compile(r"Design area.*?(\d+)%?", re.IGNORECASE)

def _parse_log_util(log_path: Path) -> list[dict]:
    """Extract area (um²) and utilization (%) from a log file."""
    if not log_path.is_file():
        return []
    text = log_path.read_text()
    for line in text.splitlines():
        if "Design area" not in line:
            continue
        nums = re.findall(r"\d+", line)
        if len(nums) >= 2:
            area = float(nums[0])
            util = float(nums[-1])
            if area > 0 and 0 < util <= 100:
                return [{"kind": "summary", "design_area_um2": area, "utilization_pct": util}]
    return []

# ─── DRC from route log ───────────────────────────────────────────────────────
_LOG_DRC = re.compile(r"(\d+)\s+drc", re.IGNORECASE)

def _parse_log_drc(log_path: Path) -> list[dict]:
    if not log_path.is_file():
        return []
    text = log_path.read_text()
    for line in text.splitlines():
        m = _LOG_DRC.search(line)
        if m:
            return [{"kind": "summary", "total_violations": int(m.group(1))}]
    return []

be = ORFSBackend(orfs_root=orfs_root)
design = DesignSpec(name=design_nm, config_path=config_p, pdk=pdk)

for stage in be.get_supported_stages():
    print(f"\n=== Stage: {stage} ===")

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    result = RunResult(
        run_id=str(uuid.uuid4()),
        backend_name="orfs",
        design_name=design_nm,
        stage=stage,
        status=StageStatus.SUCCESS,
        started_at=now,
        finished_at=now,
        report_dir=report_dir,
        params={},
    )

    run_db_id = _upsert_run(result, design)
    print(f"  Run DB id: {run_db_id}")

    # ── rpt files (timing, power, congestion, utilization) ───────────────────
    reports = be.collect_reports(result)
    if not reports:
        print(f"  [skip] No matching reports for {stage}")
    else:
        for rpt in reports:
            if not rpt.path.is_file():
                continue
            try:
                parser = get_parser(rpt.report_type)
                records = parser.parse_file(rpt.path)
                _ingest_records(records, run_db_id, stage)
                print(f"  [ok] {rpt.path.name} ({rpt.report_type}) → {len(records)} records")
            except Exception as exc:
                print(f"  [warn] {rpt.path.name}: {exc}", file=sys.stderr)

    # ── log files: area/utilization for every stage ─────────────────────────
    stage_log_map = {
        "synth":     "1_synth.log",
        "floorplan": "2_4_floorplan_pdn.log",
        "place":     "3_5_place_dp.log",
        "cts":       "4_1_cts.log",
        "route":     "5_2_route.log",
        "finish":    "6_report.log",
    }
    if stage in stage_log_map:
        log_path = log_dir / stage_log_map[stage]
        util_recs = _parse_log_util(log_path)
        if util_recs:
            _ingest_records(util_recs, run_db_id, stage)
            print(f"  [ok] {log_path.name} (utilization) → {len(util_recs)} records from log")

    # ── DRC from route log ──────────────────────────────────────────────────
    if stage == "route":
        drc_log = log_dir / "5_2_route.log"
        drc_recs = _parse_log_drc(drc_log)
        if drc_recs:
            _ingest_records(drc_recs, run_db_id, stage)
            print(f"  [ok] {drc_log.name} (drc) → {len(drc_recs)} records from log")

print("\n============================================================")
print("  QoR ingestion complete!")
print("============================================================")
PYEOF
