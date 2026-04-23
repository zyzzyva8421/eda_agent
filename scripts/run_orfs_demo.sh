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
import sys
import uuid
import datetime
import logging
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

be = ORFSBackend(orfs_root=orfs_root)
design = DesignSpec(name=design_nm, config_path=config_p, pdk=pdk)

for stage in be.get_supported_stages():
    print(f"\n=== Stage: {stage} ===")
    
    # Build a RunResult for this stage (reports are all in the same base dir)
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

    # collect_reports uses _REPORT_PATTERNS to find files in result.report_dir
    reports = be.collect_reports(result)
    if not reports:
        print(f"  [skip] No matching reports for {stage}")
        continue

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

print("\n============================================================")
print("  QoR ingestion complete!")
print("============================================================")
PYEOF
