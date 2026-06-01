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
eda-agent --version                 # Print package version
eda-agent submit --stage synth \
    --design gcd \
    --config $ORFS_ROOT/flow/designs/sky130hd/gcd/config.mk
eda-agent list [--status pending|running|success|failed|cancelled]
eda-agent status <job_id>
eda-agent logs   <job_id> [--follow]
eda-agent wait   <job_id> [--timeout SECONDS]   # block until terminal; exit-coded
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
| `INNOVUS_EXECUTION_MODE`       | Innovus execution mode: `ssh` (default), `local`, `bsub`.   |
| `INNOVUS_SSH_HOST`             | SSH hostname for remote Innovus host.                              |
| `INNOVUS_SSH_USER`             | SSH username.                                                      |
| `INNOVUS_SSH_PORT`            | SSH port (default 22).                                             |
| `INNOVUS_SSH_PASSWORD`        | SSH password (used with sshpass).                                  |
| `INNOVUS_BIN`                 | Path to Innovus binary on target host.                              |
| `INNOVUS_REMOTE_WORKDIR`      | Base working directory on remote host.                             |
| `INNOVUS_LOCAL_WORKDIR`       | Local working directory for `local`/`bsub` modes.          |
| `INNOVUS_SCHEDULER_QUEUE`     | PBS queue or Slurm partition name.                                 |
| `INNOVUS_SCHEDULER_ACCOUNT`   | Scheduler account/ project string.                                 |
| `INNOVUS_SCHEDULER_EXTRA`     | Extra raw args appended to `qsub`/`sbatch` (e.g. `--nodes=2`).     |
| `PARQUET_ARCHIVE_DIR`        | Directory for Parquet archives.                                   |
| `API_SECRET_KEY`             | 256-bit random secret for JWT signing.                            |
| `API_ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime in minutes.                                     |
| `LOG_LEVEL`                  | Default log level for the API server / worker.                    |
| `CUSTOM_TOOLS_FILE`          | Optional path to custom tool JSON config loaded at startup.       |
| `CUSTOM_TOOLS_ALLOWLIST`     | Optional comma-separated custom tool names to allow.              |
| `CUSTOM_TOOLS_DENYLIST`      | Optional comma-separated custom tool names to block.              |
| `CUSTOM_TOOLS_ENABLE_ENTRYPOINTS` | Enable Python entry points custom tools (default true).     |
| `CUSTOM_TOOLS_ENTRYPOINT_GROUP`   | Entry point group name (default `eda_agent.custom_tools`).   |
| `LLM_TOOL_CALLING_MODE`           | `native` for OpenAI-style tool calling (default), `prompt` for chat templates that do not expand the `{{ tools }}` tool placeholder. |
| `EDA_AGENT_LOG`              | Override CLI log level (`DEBUG` / `INFO` / …); takes precedence over `-v`. |
| `NO_COLOR` / `EDA_AGENT_NO_COLOR` | Disable ANSI colours in the REPL output.                     |
| `LANGSMITH_*`                | Optional LangSmith tracing.                                       |

Run `eda-agent doctor` after editing `.env` to confirm everything is wired correctly.

### Local Gemma 4 via vLLM

If you point the agent at a local vLLM server started with a plain Gemma 4
`--chat-template` such as:

```bash
MODEL_DIR=/path/to/gemma-4-model
CHAT_TEMPLATE='paste your Gemma 4 chat template here'

docker run --runtime=nvidia \
    --gpus all \
    -p 7860:8000 \
    --ipc=host \
    -e VLLM_ENABLE_CUDA_COMPATIBILITY=1 \
    -v "${MODEL_DIR}:/model" \
    vllm/vllm-openai:gemma4-cu130 \
    --model /model \
    --gpu-memory-utilization 0.88 \
    --max-model-len 65535 \
    --kv-cache-dtype fp8 \
    --tool-call-parser gemma4 \
    --enable-log-requests \
    --enable-auto-tool-choice \
    --trust-remote-code \
    --chat-template "${CHAT_TEMPLATE}"
```

Replace `/path/to/gemma-4-model` with your local model directory and replace
`paste your Gemma 4 chat template here` with the full Gemma 4 chat-template
string you pass to vLLM. For multi-line templates, use shell quoting that
preserves newlines or load the template text from a file before running
`docker run`.

Set the agent to prompt-mode tool calling:

```bash
# These MINIMAX_* settings are also used for compatible OpenAI-style local endpoints.
MINIMAX_BASE_URL=http://127.0.0.1:7860/v1
MINIMAX_API_KEY=dummy
MINIMAX_MODEL=/model
LLM_TOOL_CALLING_MODE=prompt
```

`prompt` mode is required for chat templates that only render plain
`system`/`user`/`assistant` messages and do not expand the OpenAI `tools`
payload directly.

## Custom tools (MVP)

You can define your own tools and expose them to the agent through one JSON file.

1. Create a JSON config file:

```json
{
    "tools": [
        {
            "name": "echo_note",
            "description": "Echo a note in terminal",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Text to echo"}
                },
                "required": ["message"]
            },
            "command": ["echo", "{message}"],
            "timeout_sec": 10
        }
    ]
}
```

2. Set env variable and start CLI/API:

```bash
export CUSTOM_TOOLS_FILE=/absolute/path/custom_tools.json
eda-agent
```

Notes:
- `command` is executed as argv (no shell), safer than shell string execution.
- Placeholder values use Python format style, e.g. `"{message}"`.
- Name conflicts with built-in tools are skipped automatically.

### Custom tool permissions

You can define per-tool policy in the JSON config:

```json
{
    "name": "dangerous_tool",
    "description": "...",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "command": ["echo", "x"],
    "permissions": {
        "risk_level": "warn",
        "requires_confirmation": true
    }
}
```

- `risk_level`: `safe` | `warn` | `block`
- `requires_confirmation`: if true, guardrail requires `_guardrail_confirmed=true`

### Python entry points custom tools

You can also register custom tools via Python package entry points.

Entry point group: `eda_agent.custom_tools` (or override with
`CUSTOM_TOOLS_ENTRYPOINT_GROUP`). Each entry point must provide a dict or
list of dict specs with:

- `name`
- `description`
- `parameters` (OpenAI function schema object)
- `callable` (Python callable)
- optional `permissions`

Custom tool calls are audited into DB table `custom_tool_audit`
(tool_name, arguments_summary, duration_ms, exit_code, ok, error_message).

## Custom tools rollout checklist (Phase 2)

Use this checklist when enabling custom tools in a real environment.

1. Apply latest DB migrations (includes `custom_tool_audit` table):

```bash
alembic upgrade head
```

2. Configure custom tool loading policy in `.env`:

```bash
CUSTOM_TOOLS_FILE=/abs/path/custom_tools.json
CUSTOM_TOOLS_ALLOWLIST=
CUSTOM_TOOLS_DENYLIST=
CUSTOM_TOOLS_ENABLE_ENTRYPOINTS=true
CUSTOM_TOOLS_ENTRYPOINT_GROUP=eda_agent.custom_tools
```

3. Start CLI or API and verify tool discovery with a simple custom tool call.

4. Validate guardrail behavior:
- `risk_level=warn` should execute with warnings.
- `risk_level=block` should be blocked.
- `requires_confirmation=true` should require `_guardrail_confirmed=true`.

5. Validate audit records:

```sql
SELECT tool_name, ok, duration_ms, created_at
FROM custom_tool_audit
ORDER BY created_at DESC
LIMIT 20;
```

## Innovus execution modes

The Innovus backend supports three execution modes, controlled by `INNOVUS_EXECUTION_MODE`:

### SSH (default)

```env
INNOVUS_EXECUTION_MODE=ssh
INNOVUS_SSH_HOST=innovus-server.example.com
INNOVUS_SSH_USER=eda_user
INNOVUS_SSH_PASSWORD=secret
INNOVUS_BIN=/opt/cadence/INNOVUS181/bin/innovus
INNOVUS_REMOTE_WORKDIR=/home/eda_user/innovus_work
```

Commands run over SSH on the remote host; reports are copied back via SCP.

### Local (direct execution)

```env
INNOVUS_EXECUTION_MODE=local
INNOVUS_BIN=/opt/cadence/INNOVUS181/bin/innovus
INNOVUS_LOCAL_WORKDIR=/tmp/eda_agent/innovus
```

Innovus runs on the local machine via `subprocess`. TCL scripts from `eda_agent/backends/scripts/innovus/` are copied into a per-run working directory under `INNOVUS_LOCAL_WORKDIR`. No SCP is needed.

### LSF / bsub (IBM Platform LSF)

```env
INNOVUS_EXECUTION_MODE=bsub
INNOVUS_BIN=/opt/cadence/INNOVUS181/bin/innovus
INNOVUS_LOCAL_WORKDIR=/tmp/eda_agent/innovus
INNOVUS_SCHEDULER_QUEUE=eda_queue
INNOVUS_SCHEDULER_ACCOUNT=my_project
INNOVUS_SCHEDULER_EXTRA=-R "rusage[mem=8192]"
```

The full Innovus command is passed directly to `bsub -q <queue> -Is -XF <cmd>`. The `-Is` flag allocates a pseudo-TTY and blocks until the job finishes, so the agent waits synchronously and captures the exit code directly. No wrapper script is written.

## Phase roadmap

| Phase | Goal |
|---|---|
| 1 | ORFS gcd demo → parse reports → PostgreSQL ingest |
| 2 | MiniMax Agent MVP: `query_timing` + `compare_runs` via CLI |
| 3 | Autonomous tuning loop: `run_eda_stage` + `suggest_params` ReAct |
| 4 | FastAPI + Parquet archival + additional backend stubs |
| 5 | Interactive CLI polish: persistent sessions, async job queue, verbose / streaming output |
