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
├── queue/         # Async job queue + background worker
├── diagnostics.py # `eda-agent doctor` environment checks
├── console.py     # Spinner / colour helpers for the interactive CLI
├── cli.py         # `eda-agent` entry point (REPL + subcommands)
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

### 4. Verify your environment

```bash
eda-agent doctor
```

This runs a one-shot checklist (API key, PostgreSQL connectivity, ORFS_ROOT, secrets, …) and prints actionable hints for anything that is missing or misconfigured.  Exit code is non-zero only on hard failures.

### 5. Run the ORFS gcd demo and ingest results

```bash
bash scripts/run_orfs_demo.sh
```

### 6. Start the API server

```bash
uvicorn eda_agent.api.main:app --reload
# or, equivalently:
eda-agent-server
```

### 7. Chat with the agent (CLI)

```bash
eda-agent
```

## CLI surface

`eda-agent` ships three console scripts:

| Command              | Purpose                                                     |
|----------------------|-------------------------------------------------------------|
| `eda-agent`          | Interactive REPL (default) and async-job subcommands.       |
| `eda-agent-server`   | Start the FastAPI / Uvicorn HTTP server.                    |
| `eda-agent-worker`   | Run the background job worker (also auto-started on submit).|

### Top-level flags (REPL mode)

| Flag             | Description                                                            |
|------------------|------------------------------------------------------------------------|
| `--session ID`   | Resume / create a named REPL session (default: `cli-<user>-default`).  |
| `--new`          | Start a brand-new REPL session, ignoring stored history.               |
| `--resume`       | Pick a previous REPL session from a list before starting.              |
| `--no-persist`   | Do not read or write the `agent_sessions` DB table (throwaway session).|
| `-v`, `--verbose`| Increase verbosity (`-v` → INFO + ReAct steps, `-vv` → DEBUG).         |
| `-q`, `--quiet`  | Only print final replies / errors (log level → ERROR).                 |
| `--stream`       | Stream the final assistant reply token-by-token (best-effort SSE).     |

### Subcommands

```bash
eda-agent doctor                    # Environment / connectivity checklist
eda-agent submit --stage synth \
    --design gcd \
    --config $ORFS_ROOT/flow/designs/sky130hd/gcd/config.mk
eda-agent list [--status pending|running|success|failed|cancelled]
eda-agent status <job_id>
eda-agent logs   <job_id> [--follow]
eda-agent cancel <job_id> | --all
```

`submit` returns a job id immediately and auto-starts the background worker (unless `--no-worker` is passed).  Use `logs --follow` to tail output and `status` to check the final state.

### Commands inside the REPL

| Command            | Action                                                              |
|--------------------|---------------------------------------------------------------------|
| `clear`            | Drop message history (keep design context).                         |
| `forget`           | Drop EVERYTHING and delete this session from the DB.                |
| `history [--full]` | Print message history (default: 200-char preview per message).      |
| `sessions`         | List recent sessions for the current user.                          |
| `session <id>`     | Switch to / create another session.                                 |
| `cd <dir>`         | Change the working directory of the REPL.                           |
| `!<cmd>`           | Run a shell command (e.g. `!ls`, `!pwd`, `!make synth`).            |
| `help`             | Show the in-REPL help.                                              |
| `exit` / `quit`    | Leave the REPL (also: Ctrl-D, Ctrl-C).                              |

Tab completes built-in commands, executables (after `!`), and filesystem paths.  Up/down arrows navigate persistent history (`~/.eda_agent_history`).

Anything that is not one of the built-in commands is forwarded to the ReAct agent as a free-form prompt.

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable                     | Description                                                       |
|------------------------------|-------------------------------------------------------------------|
| `MINIMAX_API_KEY`            | MiniMax API key.                                                  |
| `MINIMAX_GROUP_ID`           | MiniMax group / org id (required by some MiniMax endpoints).      |
| `MINIMAX_BASE_URL`           | Override the default MiniMax endpoint.                            |
| `MINIMAX_MODEL`              | Model identifier (default `MiniMax-Text-01`).                     |
| `POSTGRES_*`                 | PostgreSQL connection details (user / password / host / port / db).|
| `ORFS_ROOT`                  | Absolute path to OpenROAD-flow-scripts.                           |
| `ORFS_MAKE_JOBS`             | `-j` value passed to ORFS make invocations.                       |
| `INNOVUS_*`                  | Innovus SSH backend settings (optional).                          |
| `PARQUET_ARCHIVE_DIR`        | Directory for Parquet archives.                                   |
| `API_SECRET_KEY`             | 256-bit random secret for JWT signing.                            |
| `API_ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime in minutes.                                     |
| `LOG_LEVEL`                  | Default log level for the API server / worker.                    |
| `EDA_AGENT_LOG`              | Override CLI log level (`DEBUG` / `INFO` / …); takes precedence over `-v`. |
| `NO_COLOR` / `EDA_AGENT_NO_COLOR` | Disable ANSI colours in the REPL output.                     |
| `LANGSMITH_*`                | Optional LangSmith tracing.                                       |

Run `eda-agent doctor` after editing `.env` to confirm everything is wired correctly.

## Phase roadmap

| Phase | Goal |
|---|---|
| 1 | ORFS gcd demo → parse reports → PostgreSQL ingest |
| 2 | MiniMax Agent MVP: `query_timing` + `compare_runs` via CLI |
| 3 | Autonomous tuning loop: `run_eda_stage` + `suggest_params` ReAct |
| 4 | FastAPI + Parquet archival + additional backend stubs |
| 5 | Interactive CLI polish: persistent sessions, async job queue, verbose / streaming output |
