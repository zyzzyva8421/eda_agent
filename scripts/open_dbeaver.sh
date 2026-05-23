#!/usr/bin/env bash
set -euo pipefail

# Open current project database in DBeaver using POSTGRES_* from .env
# Usage:
#   scripts/open_dbeaver.sh
#   scripts/open_dbeaver.sh --print-only
#   scripts/open_dbeaver.sh --save

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

PRINT_ONLY=false
SAVE_CONNECTION=false
if [[ "${1-}" == "--print-only" ]]; then
  PRINT_ONLY=true
fi
if [[ "${1-}" == "--save" ]]; then
  SAVE_CONNECTION=true
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env not found at ${ENV_FILE}" >&2
  echo "Please create it first (for example: cp .env.example .env)." >&2
  exit 1
fi

# Export .env vars into current shell.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-eda_agent}"
POSTGRES_USER="${POSTGRES_USER:-eda_agent}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"

JDBC_URL="jdbc:postgresql://${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
PSQL_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo "Database connection info"
echo "  Host:     ${POSTGRES_HOST}"
echo "  Port:     ${POSTGRES_PORT}"
echo "  Database: ${POSTGRES_DB}"
echo "  User:     ${POSTGRES_USER}"
echo "  JDBC URL: ${JDBC_URL}"

if [[ "${PRINT_ONLY}" == "true" ]]; then
  echo
  echo "Print-only mode enabled, not launching DBeaver."
  exit 0
fi

# Validate credentials before launching GUI to avoid opaque DBeaver auth errors.
if command -v psql >/dev/null 2>&1; then
  if ! PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    -c "select 1;" >/dev/null 2>&1; then
    echo
    echo "Database login check failed with current .env credentials." >&2
    echo "Please verify POSTGRES_USER / POSTGRES_PASSWORD in .env." >&2
    exit 3
  fi
fi

DBEAVER_BIN=""
if command -v dbeaver >/dev/null 2>&1; then
  DBEAVER_BIN="dbeaver"
elif command -v dbeaver-ce >/dev/null 2>&1; then
  DBEAVER_BIN="dbeaver-ce"
fi

if [[ -z "${DBEAVER_BIN}" ]]; then
  echo
  echo "DBeaver executable not found (checked: dbeaver, dbeaver-ce)." >&2
  echo "You can still connect manually with these values:" >&2
  echo "  Host=${POSTGRES_HOST}" >&2
  echo "  Port=${POSTGRES_PORT}" >&2
  echo "  Database=${POSTGRES_DB}" >&2
  echo "  User=${POSTGRES_USER}" >&2
  echo "  Password=<POSTGRES_PASSWORD from .env>" >&2
  echo "  JDBC URL=${JDBC_URL}" >&2
  echo "  psql URL=${PSQL_URL}" >&2
  exit 2
fi

# DBeaver CLI connection string.
SAVE_VALUE="false"
if [[ "${SAVE_CONNECTION}" == "true" ]]; then
  SAVE_VALUE="true"
fi

CONN_STRING="driver=postgresql|url=${JDBC_URL}|user=${POSTGRES_USER}|password=${POSTGRES_PASSWORD}|name=EDA Agent (${POSTGRES_DB})|save=${SAVE_VALUE}"
LOG_FILE="/tmp/eda_agent_dbeaver.log"

echo
echo "Launching DBeaver via: ${DBEAVER_BIN}"
"${DBEAVER_BIN}" -con "${CONN_STRING}" >"${LOG_FILE}" 2>&1 &
disown

echo "DBeaver launch command sent."
echo "Startup log: ${LOG_FILE}"
