# EDA Agent

LLM-driven EDA agent for PPA / parameter tuning, backed by OpenROAD Flow Scripts (ORFS) with an extensible backend layer for future Innovus, ICC2, or custom PR-tool integration.

## Architecture overview

```
eda_agent/
├── backends/      # AbstractEDABackend + ORFS / Innovus(stub) / ICC2(stub)
├── parsers/       # Timing / congestion / utilization report parsers
├── db/            # SQLAlchemy + GeoAlchemy2 schema, Alembic migrations, Parquet archiver
├── agent/         # MiniMax ReAct planner, tool registry, session memory
├── api/           # FastAPI multi-user service with JWT auth
└── config.py      # Unified settings via pydantic-settings
scripts/
└── run_orfs_demo.sh   # One-shot ORFS gcd demo runner
```

## Quick start

### 1. Start PostgreSQL + PostGIS

```bash
cp .env.example .env          # edit passwords / API keys
docker compose up -d
```

### 2. Install Python dependencies

```bash
pip install -e ".[dev]"
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Run the ORFS gcd demo and ingest results

```bash
bash scripts/run_orfs_demo.sh
```

### 5. Start the API server

```bash
uvicorn eda_agent.api.main:app --reload
```

### 6. Chat with the agent (CLI)

```bash
eda-agent
```

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `MINIMAX_API_KEY` | MiniMax API key |
| `MINIMAX_GROUP_ID` | MiniMax group / org ID |
| `POSTGRES_*` | PostgreSQL connection details |
| `ORFS_ROOT` | Absolute path to OpenROAD-flow-scripts |
| `PARQUET_ARCHIVE_DIR` | Directory for Parquet archives |
| `API_SECRET_KEY` | 256-bit random secret for JWT signing |

## Phase roadmap

| Phase | Goal |
|---|---|
| 1 | ORFS gcd demo → parse reports → PostgreSQL ingest |
| 2 | MiniMax Agent MVP: `query_timing` + `compare_runs` via CLI |
| 3 | Autonomous tuning loop: `run_eda_stage` + `suggest_params` ReAct |
| 4 | FastAPI + Parquet archival + additional backend stubs |
