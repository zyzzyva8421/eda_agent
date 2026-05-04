#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Auto-load local .env so MiniMax/ORFS settings are available without manual export.
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

ORFS_ROOT_RESOLVED="${ORFS_ROOT:-${HOME}/Desktop/OpenROAD-flow-scripts}"
export PATH="${ORFS_ROOT_RESOLVED}/tools/OpenROAD/build/bin:${PATH}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/run_llm_place_timing_improvement.py" "$@"
