#!/usr/bin/env bash
# run_orfs_demo.sh – Run the ORFS gcd demo and ingest results into PostgreSQL
#
# Usage:
#   bash scripts/run_orfs_demo.sh [ORFS_ROOT] [PDK] [DESIGN]
#
# Defaults:
#   ORFS_ROOT = /home/aliu/Desktop/OpenROAD-flow-scripts
#   PDK       = sky130hd
#   DESIGN    = gcd
#
# Prerequisites:
#   - ORFS installed and its deps (openroad, yosys, klayout, etc.) on PATH
#   - Python env with eda_agent installed  (pip install -e .[dev])
#   - PostgreSQL running (docker compose up -d)
#   - .env configured (copy .env.example and edit)

set -euo pipefail

ORFS_ROOT="${1:-${ORFS_ROOT:-$HOME/OpenROAD-flow-scripts}}"
PDK="${2:-sky130hd}"
DESIGN="${3:-gcd}"
FLOW_DIR="${ORFS_ROOT}/flow"
DESIGN_CONFIG="${FLOW_DIR}/designs/${PDK}/${DESIGN}/config.mk"
MAKE_JOBS="${ORFS_MAKE_JOBS:-4}"

echo "============================================================"
echo "  EDA Agent – ORFS demo runner"
echo "  ORFS_ROOT : ${ORFS_ROOT}"
echo "  PDK       : ${PDK}"
echo "  DESIGN    : ${DESIGN}"
echo "============================================================"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [[ ! -d "${FLOW_DIR}" ]]; then
  echo "ERROR: ORFS flow directory not found: ${FLOW_DIR}"
  echo "       Set ORFS_ROOT or pass it as the first argument."
  exit 1
fi

if [[ ! -f "${DESIGN_CONFIG}" ]]; then
  echo "ERROR: Design config not found: ${DESIGN_CONFIG}"
  exit 1
fi

# ── Apply PostGIS migration (idempotent) ──────────────────────────────────────
echo ""
echo ">>> Applying database migrations …"
alembic upgrade head

# ── Run the full ORFS flow ────────────────────────────────────────────────────
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

# ── Ingest results via Python ─────────────────────────────────────────────────
echo ""
echo ">>> Ingesting reports into PostgreSQL …"

python - <<PYEOF
import sys
from pathlib import Path
from eda_agent.backends.orfs import ORFSBackend
from eda_agent.backends.base import DesignSpec, StageStatus
from eda_agent.agent.tools import _upsert_run, _ingest_records
from eda_agent.parsers import get_parser
import uuid, datetime, logging

logging.basicConfig(level=logging.INFO)

orfs_root = Path("${ORFS_ROOT}")
pdk       = "${PDK}"
design_nm = "${DESIGN}"
config_p  = Path("${DESIGN_CONFIG}")

be = ORFSBackend(orfs_root=orfs_root)
design = DesignSpec(name=design_nm, config_path=config_p, pdk=pdk)

for stage in be.get_supported_stages():
    report_dir = orfs_root / "flow" / "reports" / pdk / design_nm / stage
    if not report_dir.is_dir():
        print(f"  [skip] No report_dir for stage {stage}")
        continue

    from eda_agent.backends.base import RunResult
    result = RunResult(
        run_id=str(uuid.uuid4()),
        backend_name="orfs",
        design_name=design_nm,
        stage=stage,
        status=StageStatus.SUCCESS,
        started_at=datetime.datetime.now(tz=datetime.timezone.utc),
        finished_at=datetime.datetime.now(tz=datetime.timezone.utc),
        report_dir=report_dir,
        params={},
    )

    run_db_id = _upsert_run(result, design)
    reports   = be.collect_reports(result)
    for rpt in reports:
        try:
            parser  = get_parser(rpt.report_type)
            records = parser.parse_file(rpt.path)
            _ingest_records(records, run_db_id, stage)
            print(f"  [ok] {rpt.path.name} → {len(records)} records (run_id={run_db_id})")
        except Exception as exc:
            print(f"  [warn] {rpt.path.name}: {exc}", file=sys.stderr)

print("")
print("Ingestion complete.")
PYEOF

echo ""
echo "============================================================"
echo "  Demo finished!  Open pgAdmin at http://localhost:5050"
echo "  or run: psql -U eda_agent -d eda_agent -c 'SELECT * FROM runs;'"
echo "============================================================"
