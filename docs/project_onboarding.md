# 🧭 EDA Agent 项目交接文档

> 面向团队的项目结构 / 代码逻辑 / 调用链路速查手册。  
> 阅读完本文档后，应能：① 在 30 分钟内跑通本地环境；② 知道某个功能从哪个文件入手；③ 理解一次用户请求是如何穿过整套系统的。

---

## 📌 1. 项目定位

**EDA Agent** 是一个 **LLM 驱动的 EDA 后端自动化代理**，目标是用 ReAct (Reason + Act) 的方式驱动 OpenROAD/Innovus/ICC2 这类 PR 工具，实现：

- 🚀 自动跑 EDA 流程（synth → floorplan → place → cts → route → finish）
- 📊 自动解析报告（timing / congestion / utilization / power / DRC）入库
- 🔁 自动 PPA 调参闭环（推理 → 决策 → 执行 → 验证）
- 🧠 案例 / 经验记忆 + 多代理协作（PnR / STA / Signoff / Experiment）
- 💬 交互方式：CLI REPL、FastAPI HTTP、异步任务队列

技术栈：`Python 3.10+` · `FastAPI` · `SQLAlchemy + PostgreSQL/PostGIS` · `Alembic` · `MiniMax (OpenAI 兼容) LLM` · `pydantic-settings` · `pytest`。

---

## 🏛️ 2. 顶层架构总览

```
                ┌──────────────────────────────────────────────────┐
                │                   👤 User                        │
                └──────────────┬───────────────────┬───────────────┘
                               │ CLI               │ HTTP/JWT
                       ┌───────▼─────┐      ┌──────▼──────────┐
                       │  cli.py     │      │  api/main.py    │
                       │  (REPL)     │      │  (FastAPI)      │
                       └──────┬──────┘      └──────┬──────────┘
                              │                    │
                              ▼                    ▼
                      ┌────────────────────────────────────┐
                      │    agent/planner.py  (ReAct Loop)  │◀──┐
                      │  MiniMax LLM  ⇄  tool_calls        │   │ memory /
                      └──────────────┬─────────────────────┘   │ session
                                     │ execute_tool(name,args) │
                                     ▼                         │
              ┌──────────────────────────────────────────────┐ │
              │  agent/tools.py (Tool Dispatcher + Guardrail)│ │
              └──┬──────────┬─────────┬─────────┬───────────┘ │
                 │          │         │         │             │
        ┌────────▼──┐  ┌────▼────┐  ┌─▼─────┐  ┌▼──────────┐ │
        │ backends/ │  │parsers/ │  │  db/  │  │ queue/    │ │
        │  ORFS /   │  │ rpt →   │  │ ORM + │  │ async job │ │
        │  Innovus  │  │  rows   │  │ repo  │  │  worker   │ │
        └─────┬─────┘  └────┬────┘  └───┬───┘  └─────┬─────┘ │
              │             │           │            │       │
              ▼             ▼           ▼            ▼       │
         ┌──────────┐  ┌──────────┐  ┌───────────────┐       │
         │   ORFS   │  │ report   │  │  PostgreSQL   │───────┘
         │  Innovus │  │   files  │  │  + PostGIS    │
         └──────────┘  └──────────┘  └───────────────┘
```

> 🔑 **一句话总结**：`Planner` 让 LLM 决定要调用哪个 `tool`；`tools.py` 是所有能力的总线，把请求分发给 `backends`（跑工具）/ `parsers`（解析报告）/ `db`（落库查询）/ `queue`（异步执行）。

---

## 🗂️ 3. 仓库目录结构

```
eda_agent/                  ← Python 包（业务核心）
├── __init__.py
├── cli.py                  💻 交互式 REPL + 子命令 (submit/list/status/logs/wait/cancel)
├── console.py              🎨 ANSI 颜色 / Spinner / 输出统一封装（无第三方依赖）
├── config.py               ⚙️ pydantic-settings 单例 settings，全局环境变量入口
├── diagnostics.py          🩺 `eda-agent doctor` 一键自检（API key/DB/ORFS_ROOT/...）
├── tracing.py              🔭 LangSmith 链路追踪封装
│
├── agent/                  🧠 LLM 代理核心
│   ├── planner.py          🌀 ReAct 循环主体（MiniMax 调 LLM + 工具调度）
│   ├── memory.py           🧩 AgentMemory（短期消息 + scratchpad）+ case_memory 检索
│   ├── session_store.py    💾 把会话持久化到 agent_sessions 表（CLI & API 共享）
│   ├── tools.py            🧰 所有工具实现 + 统一 execute_tool() 分发器（最大文件之一）
│   ├── tool_schemas.py     📜 工具 JSON Schema（喂给 LLM 的 function 描述）
│   ├── tool_impl_*.py      🔧 工具实现拆分（按主题分文件，被 tools.py 引用）
│   │     ├─ tool_impl_run_stage.py        跑单个 stage
│   │     ├─ tool_impl_flow_session.py     flow 会话生命周期
│   │     ├─ tool_impl_job.py              异步 job 提交/查询/取消/日志
│   │     ├─ tool_impl_query.py            timing/congestion/util/power 查询
│   │     ├─ tool_impl_persistence.py      落库 / 写 stage_outcome / decision_trace
│   │     ├─ tool_impl_trace.py            决策追溯
│   │     ├─ tool_impl_suggest.py          参数建议（LLM + 历史）
│   │     ├─ tool_impl_tuning.py           顶层 tune 入口
│   │     ├─ tool_impl_tuning_ppa.py       PPA 多目标调优
│   │     ├─ tool_impl_tuning_congestion.py 拥塞专项调优（含 blockage）
│   │     ├─ tool_impl_tuning_eval.py      调优效果评估
│   │     ├─ tool_impl_blockage.py         add_placement_blockage 等几何操作
│   │     └─ tool_impl_multi_agent.py      多子代理调度入口
│   ├── custom_tools.py     🧱 用户自定义工具加载（JSON 配置 + entry_points）
│   ├── guardrails.py       🛡️ 工具调用安全拦截 (safe/warn/block + 二次确认)
│   ├── param_mapper.py     🎚️ Innovus PPA 可调参数定义 / 取值范围 / 影响关系
│   ├── optimization_loop.py 🔁 推理→决策→执行→验证 闭环编排（Phase A + B 串联）
│   │
│   ├── inference/          🧪 根因推理引擎 (Root Cause Inference)
│   │   ├── engine.py       infer() / confirm() 公共 API
│   │   ├── features.py     从 4 张分析表抽取 FeatureVector
│   │   ├── rules.py        Rule 定义（conditions + experiments + scoring）
│   │   └── weights.py      Phase B 反馈学习：rule 权重动态调整
│   │
│   ├── subagents/          🤝 多代理（每个 sub-agent 一个职责）
│   │   ├── base.py         AgentEnvelope / BaseSubAgent 抽象
│   │   ├── contracts.py    DecisionView / HitlGate / MultiAgentCycleResult
│   │   ├── pnr_agent.py    PnR 跑流执行
│   │   ├── sta_agent.py    时序分析（只读 query_service）
│   │   ├── signoff_agent.py 签核检查
│   │   └── experiment_agent.py 实验方案生成
│   │
│   └── services/
│       └── query_service.py  📖 给子代理用的只读查询门面
│
├── api/                    🌐 FastAPI HTTP 服务
│   ├── main.py             app 入口 + 中间件 + 路由注册（含 /health）
│   ├── auth.py             JWT 签发/校验 + 密码 hash
│   └── routers/
│       ├── auth_router.py     /auth/register、/auth/token
│       ├── runs_router.py     /runs/...  触发/查询 EDA 运行
│       ├── agent_router.py    /agent/chat 多用户会话入口
│       └── metrics_router.py  /metrics/...  timing/congestion/util/power 查询
│
├── backends/               🛠️ EDA 工具抽象层（“插件”模型）
│   ├── base.py             AbstractEDABackend / DesignSpec / StageStatus / StageResult
│   ├── orfs.py             OpenROAD-flow-scripts：subprocess + make
│   ├── innovus.py          Cadence Innovus：通过 SSH 远端执行（最完整的实现）
│   ├── icc2.py             Synopsys ICC2 stub（接口占位，待扩展）
│   └── __init__.py         backend 注册表（按名查 backend 实例）
│
├── parsers/                📑 报告解析（plain text → 结构化 dict）
│   ├── base.py             BaseParser / ParseError
│   ├── __init__.py         _PARSER_REGISTRY + get_parser(name)
│   ├── timing.py / congestion.py / utilization.py / power.py / drc.py     ← ORFS 系
│   └── innovus_*.py        ← Innovus 系（含 congestion_map 二维栅格）
│
├── db/                     🗃️ 数据库 ORM + 仓储 + 归档
│   ├── schema.py           所有表的 SQLAlchemy ORM 模型
│   ├── repository.py       EDAQueryRepository：统一分析查询入口
│   ├── archiver.py         Parquet 分区归档（backend/design/year/month）
│   ├── session.py          get_db()/get_db_dependency() 会话工厂
│   └── migrations/         Alembic 迁移（versions/0001..0013）
│
└── queue/                  ⏱️ 异步任务队列（CLI 提交 → 后台 worker 执行）
    ├── store.py            SQLite (~/.eda_agent/jobs.db) 存 Job，WAL 并发
    ├── worker.py           轮询 + 调 _run_eda_stage，PID 文件守护
    └── __main__.py         python -m eda_agent.queue 入口

tests/                      ✅ pytest 单测 + integration/（含 ORFS 端到端）
scripts/                    🔨 演示 / 手动调试脚本（非生产）
docs/                       📚 文档：api.md / multi_agent_role_mapping.md / vm_rdp_guide.md / 本文件
alembic.ini                 🧬 Alembic 配置
docker-compose.yml          🐳 起本地 PostgreSQL + PostGIS
pyproject.toml              📦 依赖 + 三个 console scripts:
                              eda-agent / eda-agent-server / eda-agent-worker
Makefile                    🛠 常用任务（lint/test/check）
pytest.ini                  pytest 默认参数（asyncio 等）
.env.example                环境变量样板
README.md                   快速上手
eda_agent_v3_design.md      架构演进设计文档
eda_agent_comparison.md     与既有方案对比
jedai_v25.1_optimized.md    优化思路记录
```

---

## 🧩 4. 关键模块速览（“出问题先看这个文件”）

### 4.1 配置与启动

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `eda_agent/config.py` | 所有环境变量收口，pydantic-settings 单例 | `settings`（全局导入） |
| `eda_agent/diagnostics.py` | `eda-agent doctor` 自检：API key / DB / ORFS / 密钥 | `run_all_checks()`, `CheckResult` |
| `eda_agent/cli.py` | REPL 主循环 + 子命令解析（submit/list/status/logs/wait/cancel） | `main()` |
| `eda_agent/console.py` | 输出/颜色/Spinner，唯一允许直接 print 的位置 | `Console`, `Spinner` |
| `eda_agent/tracing.py` | LangSmith 集成（可关） | `get_tracer`, `trace_chat`, `is_tracing_enabled` |

### 4.2 Agent 核心

| 文件 | 作用 |
|------|------|
| `agent/planner.py` | **ReAct 循环**：拼 prompt → 调 MiniMax → 解析 `tool_calls` → 执行 → 写回 → 直到 final answer。`Planner.run(user_msg)` 是唯一对外入口。 |
| `agent/memory.py` | 短期消息 + scratchpad（`context` 持久 / `_internal` 易失），并提供 `save_case` / `search_similar_cases` 给案例记忆。 |
| `agent/session_store.py` | 把 `AgentMemory` 序列化到 `agent_sessions` 表。**CLI 与 HTTP 都用它**，保证会话共享。DB 不可用时静默降级。 |
| `agent/tools.py` | **工具总线**。一份 `execute_tool(name, args, db)` 分发到 `_tool_impl_xxx`；所有 `_xxx` 函数对应一个 LLM tool 名。 |
| `agent/tool_schemas.py` | LLM 看到的 JSON schema。新增工具时**两边都要改**：schema + dispatcher。 |
| `agent/guardrails.py` | `check(tool_name, args)` 返回 SAFE/WARN/BLOCK；带 `requires_confirmation` 二次确认。 |
| `agent/custom_tools.py` | 加载 `CUSTOM_TOOLS_FILE` JSON 和 Python entry_points 自定义工具，自动写 `custom_tool_audit` 审计。 |
| `agent/param_mapper.py` | Innovus 调参字典：参数→范围→影响 PPA 维度。`suggest_params` / `tune_ppa` 用它做参数过滤与映射。 |
| `agent/optimization_loop.py` | `OptimizationLoop`：把推理引擎（Phase A）和反馈学习（Phase B）串成闭环。 |

### 4.3 推理 & 多代理

| 文件 | 作用 |
|------|------|
| `agent/inference/engine.py` | 公共 API：`infer(run_id, symptoms)` → `confirm(inference_id, cause_id)`，落 `root_cause_inferences` & `case_memory`。 |
| `agent/inference/features.py` | 从 5 张分析表抽数值特征。 |
| `agent/inference/rules.py` | 每条规则：`conditions/anti_conditions/experiments`，加权打分。 |
| `agent/inference/weights.py` | 规则权重持久化 + 反馈学习。 |
| `agent/subagents/*` | PnR / STA / Signoff / Experiment 子代理，统一通过 `AgentEnvelope` 通信。`tool_impl_multi_agent.py` 是入口。 |
| `agent/services/query_service.py` | 只读查询门面，给子代理用，避免它们直接接 ORM。 |

### 4.4 Backend / Parser / DB / Queue

| 文件 | 作用 |
|------|------|
| `backends/base.py` | 抽象类 `AbstractEDABackend.run_stage(...) -> StageResult`，所有后端必须实现。 |
| `backends/orfs.py` | `make <stage>` + 日志捕获 + 报告路径索引。 |
| `backends/innovus.py` | SSH 远端 Innovus（最完整，660 行，含 workdir/license 处理）。 |
| `backends/icc2.py` | 占位 stub，待团队补全。 |
| `parsers/__init__.py` | 注册表 `get_parser("timing")` 等。 |
| `parsers/timing.py` 等 | 把 `*.rpt` / `*.log` 解析成 dict，再由 `tool_impl_persistence` 写入对应表。 |
| `db/schema.py` | ORM 表全集（见下节数据模型）。 |
| `db/repository.py` | `EDAQueryRepository`：所有分析 SQL 集中地，路由层不写 raw SQL。 |
| `db/archiver.py` | 把历史 run 按 backend/design/年/月 导出为 Parquet。 |
| `db/session.py` | `get_db()` 上下文管理 + FastAPI `Depends(get_db_dependency)`。 |
| `queue/store.py` | SQLite Job 表（WAL 并发安全），状态机：pending→running→success/failed/cancelled。 |
| `queue/worker.py` | 长驻进程，轮询 + 调 `tools._run_eda_stage`，写 PID 文件 `~/.eda_agent/worker.pid`。 |

### 4.5 API 层

| 路由 | 文件 | 主要端点 |
|------|------|----------|
| `/auth` | `api/routers/auth_router.py` | `POST /register`, `POST /token` (OAuth2 PasswordBearer) |
| `/runs` | `api/routers/runs_router.py` | `POST /runs/stage`（触发 stage）, list/查询 |
| `/agent` | `api/routers/agent_router.py` | `POST /agent/chat`（持久会话 + Planner） |
| `/metrics` | `api/routers/metrics_router.py` | `GET /metrics/timing` 等，包装 `execute_tool` |
| `/health` | `api/main.py` | 健康检查 |

---

## 🔁 5. 关键调用时序

### 5.1 CLI 一次自由对话（`eda-agent` → ReAct）

```
User keystroke
   │
   ▼
cli.py:main() ── REPL 循环 ──▶ Planner(session=...).run(prompt)
                                │
                                ├─ memory.load_session() ◀── session_store
                                ├─ build messages (system+history+context)
                                ├─ httpx.post MiniMax /chat/completions
                                │   (附带 TOOL_SCHEMAS)
                                ▼
                          response.tool_calls? ──no──▶ final text ──▶ user
                                │ yes
                                ▼
                        for call in tool_calls:
                            guardrails.check(...)
                            execute_tool(name, args, db)
                                │
                                ├─ tools.py 分发 → tool_impl_*
                                ├─ backends/* 跑 EDA
                                ├─ parsers/* 解析报告
                                └─ db/repository 落库/查询
                        append tool message → 回到 loop
```

### 5.2 异步任务（`eda-agent submit`）

```
eda-agent submit --stage place --design gcd ...
   │
   ▼
cli.py ── queue.store.put_job(...) ── SQLite ~/.eda_agent/jobs.db
   │
   └── _ensure_worker_running()  (在 tools.py)
            │
            ▼  detached subprocess
        eda-agent-worker
            │
            └── while True:
                 job = store.claim_next()
                 tools._run_eda_stage(...)
                     ├─ backends.run_stage(...)
                     ├─ parsers.* + repository.save_*
                     └─ store.set_status(success|failed)
```

CLI 端 `eda-agent status/logs/wait` 只读 SQLite，不阻塞 worker。

### 5.3 HTTP 一次 `/agent/chat`

```
POST /agent/chat  {message, session_id}
        │ Authorization: ******
        ▼
api.auth.get_current_user(token) ──▶ users 表
        │
        ▼
agent_router.chat()
   ├─ session_store.load_session(user_id, session_id)
   ├─ planner = Planner(memory=...)
   ├─ reply = planner.run(message)
   ├─ session_store.save_session(...)
   └─ return {reply, session_id, tool_trace?}
```

### 5.4 优化闭环（`tune_ppa` / `OptimizationLoop`）

```
tune_ppa(design, target_spec)
   │
   ▼
loop:
   1. _run_eda_stage(...)                  ── backends + parsers + DB
   2. infer_root_cause(run_id, symptoms)   ── inference.engine.infer()
        ├─ features.extract(run_id)
        ├─ rules.score(features) × weights.multiplier
        └─ 写 root_cause_inferences
   3. _suggest_params(run_id, target_spec) ── LLM + param_mapper
   4. _record_decision_trace(...)          ── decision_trace 表
   5. 跑下一轮，重复直到达成目标 / 触发上限
   6. confirm_root_cause(...) → case_memory  (供下次相似场景检索)
```

---

## 🗃️ 6. 数据模型一览（`db/schema.py`）

```
┌─ Backend ──┐                                  ┌─ AgentSession (CLI/HTTP 共享会话)
└────────────┘                                  ├─ CustomToolAudit (自定义工具审计)
       │ 1..n                                   ├─ RuleWeight (Phase B 权重)
┌─ Design ──┐                                   ├─ CaseRecord (case_memory)
└─────┬─────┘                                   ├─ User (auth)
      │ 1..n
┌─ FlowSession (一次完整 PnR 流程的根) ──┐
└──────┬───────────────────────────────────┘
       │ 1..n
┌─ Run (单个 stage 一次执行) ────────────────────────────────────────────────────┐
└──┬───────┬───────────┬───────────┬─────────────┬───────────┬─────────┬───────┘
   │       │           │           │             │           │         │
   ▼       ▼           ▼           ▼             ▼           ▼         ▼
 Timing  Timing    Congestion  Utilization    Power      DRC      Artifact /
 Summary Paths     Hotspot     Summary        Summary    Violation StageOutcome
                   (PostGIS)                                       / DecisionTrace
                                                                   / RootCauseInference
```

- 空间表 `congestion_hotspots` 用 PostGIS（`geometry(Polygon)`）→ 支持 `_query_congestion` 的 bbox 查询。
- `flow_sessions` / `stage_outcomes` / `decision_trace` 是 v3 设计的“可追溯实验”三件套。
- `case_memory` 由 `agent.memory.save_case` 写入，`search_similar_cases` 用文本相似度召回。
- 迁移文件 `db/migrations/versions/0001_..._0013_*.py` 与上述特性一一对应，**新增字段必须走 Alembic**。

---

## 🛠️ 7. 开发上手 Cheat Sheet

### 7.1 起本地环境

```bash
cp .env.example .env                  # 填 MINIMAX_API_KEY、POSTGRES_*、ORFS_ROOT 等
docker compose up -d                  # 起 PostgreSQL + PostGIS
pip install -e ".[dev]"
alembic upgrade head                  # 应用所有迁移
eda-agent doctor                      # 一键体检
```

### 7.2 跑测试 / Lint / 构建

```bash
make check PYTHON=python3             # ⚠️ 默认 PYTHON=python3.13，本机没有时务必显式覆盖
# 或单跑：
pytest -q
ruff check .
```

> 💡 Makefile 默认 `PYTHON=python3.13`，多数机器没有，**永远用 `make check PYTHON=python3`**。

### 7.3 常用入口

```bash
eda-agent                    # REPL（默认）
eda-agent --new              # 全新会话
eda-agent submit --stage place --design gcd --config $ORFS_ROOT/.../config.mk
eda-agent status <job_id>
eda-agent logs <job_id> --follow
uvicorn eda_agent.api.main:app --reload   # 起 API（或 eda-agent-server）
eda-agent-worker                          # 起后台 worker（submit 时也会自动拉起）
```

### 7.4 加一个新功能的“肌肉记忆”

| 需求 | 改这些文件 |
|------|------------|
| **新 EDA Backend**（如 OpenLane） | `backends/openlane.py` 继承 `AbstractEDABackend` → 在 `backends/__init__.py` 注册 |
| **新报告解析** | `parsers/<tool>_<kind>.py` 继承 `BaseParser` → 在 `parsers/__init__.py` 注册 → `tool_impl_persistence.py` 写入对应表 |
| **新 LLM 工具** | ① `tool_schemas.py` 加 JSON schema ② `tool_impl_xxx.py` 写实现 ③ `tools.py` 在 `execute_tool` 中分发 ④ 评估是否需要 `guardrails` 策略 |
| **新数据库字段/表** | `db/schema.py` 改 ORM → `alembic revision -m "..."` → 编辑生成的 `versions/00XX_*.py` → `alembic upgrade head` |
| **新 HTTP 端点** | 在 `api/routers/` 新建或扩展 router，`api/main.py` 里 `include_router` |
| **新子代理** | 继承 `subagents/base.py:BaseSubAgent`，沿用 `AgentEnvelope` 通信契约，注册到 `tool_impl_multi_agent.py` |
| **新自定义用户工具**（不改 Python） | 写 JSON 配置 + `export CUSTOM_TOOLS_FILE=...`，详见 README 「Custom tools」 |

### 7.5 调试技巧

- `eda-agent -vv` → DEBUG 级日志 + 打印每一步 ReAct。
- `eda-agent --stream` → SSE 流式回答。
- LangSmith：设置 `LANGSMITH_*` 环境变量后，所有 LLM 调用与工具调用都会上报，便于看完整 trace。
- 关掉颜色：`NO_COLOR=1` 或 `EDA_AGENT_NO_COLOR=1`。
- 异步 worker 卡住？`cat ~/.eda_agent/worker.pid` 看 PID，必要时 `kill` 后由 submit 自动重启。

---

## 🧭 8. 推荐阅读顺序（新成员上手路径）

1. 📘 `README.md`（10 min）—— 全景 + 快速跑通  
2. 📐 `eda_agent_v3_design.md`（30 min）—— 设计动机与演进  
3. 🧠 `agent/planner.py` → `agent/tools.py` → 任一 `tool_impl_*.py`（理解一次 ReAct 全链路）  
4. 🛠️ `backends/base.py` → `backends/orfs.py` / `backends/innovus.py`（理解 EDA 抽象）  
5. 🗃️ `db/schema.py` → `db/repository.py` + `parsers/*`（理解数据如何沉淀）  
6. 🧪 `agent/inference/*` + `agent/optimization_loop.py`（理解闭环调优）  
7. 🌐 `api/main.py` + `api/routers/*`（理解多用户 HTTP 入口）  
8. ⏱️ `queue/store.py` + `queue/worker.py`（理解异步 job）  
9. ✅ 浏览 `tests/`，对照你要改的模块找对应测试文件（命名规则 `test_<module>.py`）

---

## ⚠️ 9. 易踩坑提醒

- 🧪 **`make check` 默认 Python 版本是 3.13**，本机没有就显式 `PYTHON=python3`。  
- 🔐 **`API_SECRET_KEY` 必须设置**（JWT 签名），否则 API 启动会失败 / token 不可用。  
- 🐘 **PostGIS 是硬依赖**：`congestion_hotspots` 用了 `geometry`，本地起库走 `docker-compose.yml` 最稳。  
- 🧷 **DB 不可用时 `session_store` 会静默降级**——CLI 还能跑，但**会话不会持久化**，排查时别忽略。  
- 🧰 **新增工具一定要同时改 `tool_schemas.py` + `tools.execute_tool` 分发**，否则 LLM 看得到但调不到，或反之。  
- 🛡️ **危险工具走 `guardrails`**：写入文件系统 / 远程 SSH / 跑长任务的工具，务必标 `WARN` 或 `requires_confirmation`。  
- 🧬 **改 ORM 一定走 Alembic**，不要手动 `CREATE TABLE`；CI 会按 migration 链重建。  
- 🤖 **自定义工具命名冲突会被自动跳过**（custom_tools.py），命名前先查 `tool_schemas.py`。

---

## 📮 10. 联系人 & 反馈

- 📂 设计文档：`eda_agent_v3_design.md` / `eda_agent_v3_design.pdf`  
- 🆚 方案对比：`eda_agent_comparison.md`  
- 🧷 优化笔记：`jedai_v25.1_optimized.md`  
- 🤝 多代理角色分工：`docs/multi_agent_role_mapping.md`  
- 🖥️ 远程 VM 调试：`docs/vm_rdp_guide.md`  
- 🌐 API 详情：`docs/api.md`

> 有任何疑问、想补充示例图或时序图、想把某段 ReAct 真实日志贴进来举例，欢迎直接在本文件 PR；本文件被定位为 **活文档**，请大家随手维护 🚀。
