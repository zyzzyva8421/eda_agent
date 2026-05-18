# EDA Agent 技术对比分析

## 1. 项目定位

**EDA Agent** 是一个基于大语言模型（LLM）的 EDA 设计自动化 agent，专注于 PPA（功耗-性能-面积）优化和参数调优。

## 2. 系统架构

```
eda_agent/
├── backends/      # AbstractEDABackend + ORFS / Innovus / ICC2
├── parsers/       # Timing / congestion / utilization report parsers
├── db/            # SQLAlchemy + GeoAlchemy2 schema, Alembic migrations, Parquet archiver
├── agent/         # MiniMax ReAct planner, tool registry, session memory
├── api/           # FastAPI multi-user service with JWT auth
└── config.py      # Unified settings via pydantic-settings
```

### ReAct Planner 工作流程

1. **Reason**: LLM 分析当前设计状态
2. **Act**: 选择工具（如 `suggest_params`）
3. **Execute**: 调用 `run_eda_stage` 运行阶段
4. **Observe**: 解析报告，结果反馈给 LLM
5. 迭代直到收敛或达到 `max_iterations`

## 3. 实际使用场景

### 场景 1: Timing 优化

- **目标**: 优化 design 的 setup time
- **流程**:
  1. 查询当前 WNS（Worst Negative Slack）
  2. LLM 分析时序瓶颈路径
  3. 生成 Place 参数建议（如 `PLACE_DENSITY`）
  4. 重新运行 Place + Route
  5. 比较 WNS 改进，若未收敛继续迭代

### 场景 2: Congestion 优化

- **目标**: 解决局部拥塞热点
- **流程**:
  1. 解析 `congestion_map` 报告
  2. 提取热点 bounding box 坐标
  3. LLM 分析拥塞原因
  4. 生成修复参数建议
  5. 重新 Place，验证是否解决

## 4. 与 v3 设计文档的差距

| 特性 | v3 设计 | 当前实现 | 状态 |
|---|---|---|---|
| **多层架构** | UI → Planner → KG → Inference → Primitives → Adapters | CLI/API → Agent → Backends | ✅ |
| **ReAct Planner** | Reason + Act 循环 | MiniMax ReAct Planner | ✅ |
| **Case Memory** | symptom-cause-action-metrics | Session Memory | ✅ |
| **Guardrails** | 风险操作拦截 + 人类确认 | 基础 Risk Strategy | ⚠️ |
| **多 Agent** | PnR/STA/Signoff/Experiment Agent | 单一 Planner | ⚠️ |
| **Knowledge Graph** | 物理现象-参数-设计结构图 | ❌ | ❌ |
| **Root Cause Inference** | 特征提取 + 因果推理规则 | ❌ | ❌ |
| **Recipe Search** | Bayesian/RL 参数搜索 | ❌ | ❌ |

## 5. 与 ME (TPE) 工具对比

| 维度 | ME (TPE) | EDA Agent (LLM) |
|---|---|---|
| **优化方法** | TPE/Bayesian 优化 | LLM ReAct 推理 |
| **参数选择** | 数学建模 + Optuna | 自然语言推理 |
| **上下文理解** | 数值特征 | 语义理解 |
| **根因分析** | 回归模型 | LLM 推理 |
| **灵活扩展** | 参数需预先定义 | NLP 自然扩展 |
| **多目标** | Pareto 前沿 | LLM 多目标权衡 |
| **知识复用** | Trial 历史 | Case Memory |
| **成本** | 计算密集 | API 调用 |

**结论**: ME 适合固定参数空间的数值优化，EDA Agent 适合复杂场景推理。两者可互补。

## 6. 与 JedAI Platform 数据库设计对比

### JedAI Platform

| 特性 | 设计 |
|---|---|
| **存储** | NFS / 本地文件系统 |
| **元数据** | Catalog Service 管理 |
| **分析引擎** | Pandas / Spark ETL |
| **权限模型** | Role-Entity-Policy (完整) |
| **数据注册** | 通过 Catalog API 手动注册 |
| **大规模分析** | Spark 分布式计算 |
| **特点** | 通用数据平台，非 EDA 专用 |

### EDA Agent

| 特性 | 设计 |
|---|---|
| **存储** | PostgreSQL + Parquet |
| **元数据** | SQLAlchemy ORM 模型 |
| **解析器** | 结构化 report → dict |
| **权限** | 基础 JWT |
| **数据注册** | Agent 自动解析入库 |
| **大规模分析** | 本地 Parquet 查询 |
| **特点** | EDA 专用，���动化程度高 |

### 关键差异

| 维度 | JedAI | EDA Agent |
|---|---|---|
| **数据模型** | 通用数据集 | PPA 指标专用 |
| **自动解析** | 手动上传 | Agent 自动调用解析器 |
| **权限体系** | 完整 RBAC | 基础 JWT |
| **扩展性** | Catalog API | 代码级扩展 ORM |
| **场景** | 通用分析 | 自动调参优化 |

## 7. 技术亮点

1. **ReAct Planner** - LLM 自主决策调整策略
2. **多维度解析器** - 支持 Timing、Power、DRC、Congestion、Utilization
3. **Session Memory** - 记住历史调参经验
4. **Guardrails** - 安全约束，防止破坏性操作
5. **Parquet 归档** - 高效存储历史数据

## 8. 路线图

| Phase | 目标 | 状态 |
|---|---|---|
| Phase 1 | ORFS gcd demo → 解析 → 入库 | ✅ |
| Phase 2 | CLI Agent MVP (query/compare) | ✅ |
| Phase 3 | 自主调参闭环 | 🔄 |
| Phase 4 | FastAPI + 多后端生产 | 📋 |

## 9. 完整架构图

```mermaid
graph TD
    subgraph "用户接口层"
        CLI[CLI Tool<br/>eda_agent/cli.py]
        API[REST API<br/>eda_agent/api/]
    end
    
    subgraph "核心 Agent 层"
        AG[Agent Core<br/>agent/]
        PL[Planner<br/>agent/planner.py]
        MEM[Memory<br/>agent/memory.py]
        GR[Guardrails<br/>agent/guardrails.py]
        TOOLS[Tools<br/>agent/tools.py]
        INF[Inference<br/>agent/inference/]
    end
    
    subgraph "后端集成层"
        BE[Backends<br/>backends/]
        IN[Innovus<br/>backends/innovus.py]
        IC[ICC2<br/>backends/icc2.py]
        OR[OpenROADS<br/>backends/orfs.py]
    end
    
    subgraph "解析器层"
        PS[Parsers<br/>parsers/]
        TM[Timing Parser<br/>parsers/timing.py]
        PWR[Power Parser<br/>parsers/power.py]
        DRC[DRC Parser<br/>parsers/drc.py]
        CG[Congestion Parser<br/>parsers/congestion.py]
        UT[Utilization Parser<br/>parsers/utilization.py]
    end
    
    subgraph "数据层"
        DB[Database<br/>db/]
        Q[Queue System<br/>queue/]
    end
    
    CLI --> AG
    API --> AG
    AG --> PL
    AG --> MEM
    AG --> GR
    AG --> TOOLS
    TOOLS --> INF
    INF --> BE
    BE --> IN
    BE --> IC
    BE --> OR
    IN --> PS
    PS --> TM
    PS --> PWR
    PS --> DRC
    PS --> CG
    PS --> UT
    AG --> DB
    AG --> Q
```

## 10. ReAct Planner 工作流程图

```mermaid
flowchart TD
    subgraph "User Input"
        U[用户请求\n优化 gcd design 的 timing]
    end
    
    subgraph "ReAct Planner Loop"
        P1[1. Reason<br/>LLM 分析问题]
        P2[2. Act<br/>选择并调用工具]
        P3[3. Execute<br/>执行工具<br/>run_eda_stage]
        P4[4. Observe<br/>解析结果<br/>query_timing]
        P5{迭代条件<br/>max_iterations?}
        P6[5. Answer<br/>返回最终结果]
    end
    
    subgraph "Tools"
        T1[run_eda_stage]
        T2[query_timing]
        T3[compare_runs]
        T4[suggest_params]
    end
    
    U --> P1
    P1 --> P2
    P2 --> T1
    T1 --> P3
    P3 --> T2
    T2 --> P4
    P4 --> P1
    P1 --> P5
    P5 -->|未达上限| P1
    P5 -->|已达上限| P6
```

## 11. 推荐优先级

### 高优先级
- Knowledge Graph + Root Cause Inference（核心价值）

### 中优先级
- 多 Agent 协作 + Recipe Search（扩展能力）

### 低优先级
- 可视化面板（展示用）
