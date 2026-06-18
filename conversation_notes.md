# 对话全文整理（Multi-Agent / 知识图谱）

---

## Q1：如何让 Multi-agent 成为一个强协作实体？

### 当前架构的协作弱点

1. **完全独立分发（无上下文传递）**
   `_dispatch_subagents()` 对每个 agent 发送完全相同的 `inputs`，PnR Agent 的推断结果不会传给 STA Agent，STA 的约束警告也不会影响 SignoffAgent 的判断。各 agent 在信息孤岛中运行。

2. **合并逻辑是简单收集，不是综合推理**
   `_merge_agent_outputs()` 仅做 `by_agent[name] = outputs`，没有跨 agent 的矛盾检测、置信度加权或共识生成。

3. **ExperimentAgent 是空壳**
   仅从 `inputs` 里读取 `risk_level`，不根据 PnR/STA/Signoff 的真实结论来推断下一步实验。

4. **决策视图（`_build_decision_view`）是固定映射**
   直接从固定 agent 槽位取数据，无法在某个 agent 失败或未选中时降级。

5. **HITL Gate 过于简单**
   仅看 `experiment.risk_level`，忽略了 STA 的 `negative_wns`、Signoff 的 `drc_hotspots` 等多维风险信号。

---

### 增强方案

#### 1. 流水线式上下文传播（Pipeline Chaining）

**现状**：所有 agent 并行收到同样的 `inputs`。
**改为**：按依赖顺序传递，前一个 agent 的 `outputs` 注入后一个 agent 的 `inputs`。

```
PnRAgent.outputs → STAAgent.inputs（传入 candidate_experiments, hypotheses）
STAAgent.outputs → SignoffAgent.inputs（传入 constraint_warnings）
{PnR+STA+Signoff}.outputs → ExperimentAgent.inputs（综合后的风险+候选实验）
```

核心修改：在 `_dispatch_subagents()` 中维护一个 `accumulated_inputs` 字典，每步累加。

---

#### 2. 共享黑板（Shared Blackboard）

在 `AgentEnvelope` 或 `task` 字典中增加一个 `shared_board: dict` 字段，所有 agent 可以读写。这让 PnR 能发布"发现了 congestion hotspot"，STA 能消费它并关联到相应的时序路径，而无需显式的依赖顺序。

---

#### 3. 多维 HITL Gate

`_apply_hitl_gate()` 当前只看 `experiment.risk_level`。应综合多个信号：

| 信号 | 来源 | 阻断条件 |
|------|------|----------|
| `risk_level == "high"` | ExperimentAgent | 需审批 |
| `negative_wns` | STAAgent | 需审批 |
| `drc_hotspots` 非空 | SignoffAgent | 需审批 |
| `has_error` | 任意 agent | 拦截实验 |
| `signoff_ready == False` | SignoffAgent | 拦截自动执行 |

---

#### 4. ExperimentAgent 真正基于综合结论工作

ExperimentAgent 应成为"决策合成者"，接收来自其他三个 agent 的全量输出，按规则生成具体实验方案：

- 若 PnR 的 `hypotheses` 中有 `routing_detour` 且 STA 报告 `negative_wns`，则提议降低布局密度实验
- 若 Signoff 报告 `utilization_pct > 85`，则提议增加缓冲层实验
- `requires_approval` 应基于综合风险而非单一 `risk_level` 字段

---

#### 5. 案例记忆驱动的协作初始化

目前 `search_similar_cases()` 已存在但未在多 agent 循环中使用。应在 `run_multi_agent_cycle()` 开始时检索相似案例，并将案例中的 `actions` 和 `root_cause` 注入 `task.inputs`，让每个 agent 从历史经验出发而不是从零开始。

---

#### 6. 动态 Agent 选择与降级

当前 `agents` 默认为全选 4 个。应支持：
- 根据 `objective` 的关键词自动决定激活哪些 agent（timing 相关问题不必跑 SignoffAgent）
- 某 agent 报 `error` 时，其下游依赖 agent 能感知并降级运行，而非收到空 inputs

---

#### 7. 合并逻辑升级为矛盾检测与置信度加权

`_merge_agent_outputs()` 可增加：
- **矛盾检测**：PnR 认为可以自动执行，但 SignoffAgent 认为 `signoff_ready=False`，此时应升级为需审批
- **覆盖度统计**：有多少 agent 对同一结论达成一致
- **结构化综合结果**：生成一个 `consensus` 字段而非只有 `by_agent`

---

### 总结

| 协作能力 | 现状 | 目标 |
|---------|------|------|
| 上下文传递 | ❌ 独立运行 | ✅ 流水线传播 |
| 共享工作记忆 | ❌ 无 | ✅ 黑板模型 |
| 多维风险门控 | ⚠️ 单信号 | ✅ 综合多 agent 信号 |
| 实验决策合成 | ❌ 空壳 | ✅ 基于全量结论 |
| 历史案例引导 | ⚠️ 存在但未接入 | ✅ 初始化注入 |
| 动态路由 | ❌ 固定全选 | ✅ 按问题类型选择 |
| 合并综合推理 | ❌ 简单收集 | ✅ 矛盾检测+共识生成 |

最核心的一步是**流水线式上下文传播**：让 ExperimentAgent 真正看到其他三个 agent 的完整输出，它才能提出有意义的实验建议，整个 multi-agent 循环才会形成实质性的协作而非并行独白。

---

## Q2：如何实现独立图谱建模 / 存储 / 查询模块？

### 现状分析

当前代码库的「知识推理」完全依赖 `inference/rules.py` 中的硬编码 `Rule` 对象——规则知识散布在 Python 类中，没有图结构、没有边关系，`cause_id` 之间的因果链只存在于 `eda_agent_v3_design.md` 的文字描述里，无法被查询遍历。

---

### 模块边界定义

新模块路径：`eda_agent/knowledge_graph/`，作为**独立子包**，不依赖 `agent/` 层，只依赖 `db/`。

```
eda_agent/knowledge_graph/
├── __init__.py          # 公开 API：add_node, add_edge, query_causes, query_path
├── model.py             # 节点/边的数据类定义
├── store.py             # PostgreSQL 持久化层
├── query.py             # 图遍历与路径查询
└── seed.py              # 内置 EDA 领域知识的初始图谱数据
```

---

### 1. 图模型设计（model.py）

**节点类型**：EDA 领域的现象/概念
```
NodeKind: violation | phenomenon | parameter | metric | structure
```

**边类型**：因果/影响关系
```
EdgeKind: causes | contributes_to | fixed_by | indicates | correlates
```

**示例图谱**（对应 v3_design.md 中的链）：
```
high_density  → [causes]         → congestion
congestion    → [causes]         → routing_detour
routing_detour → [contributes_to] → long_net_delay
long_net_delay → [causes]        → setup_violation
cts_imbalance  → [causes]        → clock_skew
clock_skew     → [causes]        → hold_violation
```

数据类定义：
```python
@dataclass
class KGNode:
    node_id: str          # e.g. "congestion", "setup_violation"
    kind: NodeKind
    display_name: str
    description: str
    properties: dict      # e.g. {"domain": "routing", "layer": "global"}

@dataclass
class KGEdge:
    edge_id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    weight: float = 1.0   # causal strength
    conditions: dict = {}  # optional threshold guards
    evidence_rule_ids: list[str] = []  # 关联的 Rule id（如 "routing_detour"）
```

---

### 2. 数据库存储设计（store.py + migration）

新增两张表，继承现有 `Base`，遵守仓库 JSON/JSONB 兼容约定：

**`kg_nodes`**

| 列 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| node_id | VARCHAR(128) UNIQUE | 业务 ID |
| kind | VARCHAR(32) | |
| display_name | VARCHAR(256) | |
| description | TEXT | |
| properties | JSON/JSONB | 使用 `supports_postgresql_jsonb()` 门控 |
| created_at | TIMESTAMP | |

**`kg_edges`**

| 列 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| edge_id | VARCHAR(128) UNIQUE | |
| source_id | VARCHAR(128) FK→kg_nodes.node_id | |
| target_id | VARCHAR(128) FK→kg_nodes.node_id | |
| kind | VARCHAR(32) | |
| weight | FLOAT DEFAULT 1.0 | |
| conditions | JSON/JSONB | |
| evidence_rule_ids | JSON/JSONB | 与 `rule_weights.rule_id` 关联 |
| created_at | TIMESTAMP | |

新建 migration `0014_add_knowledge_graph.py`，索引 `(source_id, kind)` 和 `(target_id, kind)` 支持图遍历。

**`store.py` 核心接口**：
```python
def upsert_node(node: KGNode) -> None
def upsert_edge(edge: KGEdge) -> None
def get_node(node_id: str) -> KGNode | None
def get_edges_from(source_id: str, kind: EdgeKind | None = None) -> list[KGEdge]
def get_edges_to(target_id: str, kind: EdgeKind | None = None) -> list[KGEdge]
```

---

### 3. 查询层设计（query.py）

三类查询，纯 Python 图遍历（不依赖 PostgreSQL 图扩展）：

**① 因果路径查询** `find_causal_path(source_id, target_id, max_depth=5)`
- BFS/DFS 遍历 `causes` / `contributes_to` 边
- 返回路径列表：`[["high_density", "congestion", "routing_detour", "setup_violation"]]`
- 用于：给定已知根因，追溯到哪些 violation

**② 根因候选查询** `find_root_causes(symptom_id, max_depth=3)`
- 从 violation 节点**反向**遍历（沿 `causes` 边逆向）
- 返回所有到达 symptom 的起点节点及路径
- 用于：增强 `inference/engine.py` 的 `infer()` — 先用图谱缩小规则集范围

**③ 修复建议查询** `find_fixes(node_id)`
- 遍历 `fixed_by` 边，返回关联的 `parameter` 节点
- 连接 `evidence_rule_ids` 查 `ExperimentSuggestion`

**④ 子图提取** `subgraph(center_id, depth=2)`
- 返回以某节点为中心的邻域子图（节点列表 + 边列表）
- 用于：前端可视化/LLM 上下文注入

---

### 4. 种子数据（seed.py）

把 `inference/rules.py` 中现有的 6 条规则转化为图谱种子：

```python
SEED_NODES = [
    KGNode("high_density",    "phenomenon", "High Placement Density", ...),
    KGNode("congestion",      "phenomenon", "Routing Congestion", ...),
    KGNode("routing_detour",  "phenomenon", "Routing Detour", ...),
    KGNode("long_net_delay",  "metric",     "Long Net Delay", ...),
    KGNode("setup_violation", "violation",  "Setup Timing Violation", ...),
    KGNode("cts_imbalance",   "phenomenon", "CTS Clock Tree Imbalance", ...),
    KGNode("clock_skew",      "metric",     "Clock Skew", ...),
    KGNode("hold_violation",  "violation",  "Hold Timing Violation", ...),
    # ... 对应 CORE_UTILIZATION, PLACE_DENSITY 等参数节点
]

SEED_EDGES = [
    KGEdge("e1", "high_density",   "congestion",      "causes",         weight=0.8, evidence_rule_ids=["routing_detour", "density_saturation"]),
    KGEdge("e2", "congestion",     "routing_detour",  "causes",         weight=0.9, evidence_rule_ids=["routing_detour"]),
    KGEdge("e3", "routing_detour", "setup_violation", "contributes_to", weight=0.7, evidence_rule_ids=["routing_detour"]),
    # ...
]
```

提供 `seed_graph()` 函数供 `alembic` 迁移或 CLI 初始化调用。

---

### 5. 与现有模块的集成点

| 集成位置 | 方式 | 效果 |
|---------|------|------|
| `inference/engine.py::infer()` | 调用 `query.find_root_causes(symptom_id)` 预筛选规则 | 图谱驱动的规则激活，而非盲评所有规则 |
| `agent/subagents/pnr_agent.py` | 调用 `query.subgraph("congestion", depth=2)` | 向 LLM 注入结构化因果上下文 |
| `agent/planner.py::_build_system_prompt()` | 将路径查询结果序列化注入 system prompt | LLM 有完整的因果链知识 |
| `agent/memory.py::save_case()` | 存 case 时同时更新图谱边的 weight | 实战反馈强化图谱边强度 |

---

### 6. 公开 API（`__init__.py`）

```python
from .store import upsert_node, upsert_edge, get_node, get_edges_from, get_edges_to
from .query import find_causal_path, find_root_causes, find_fixes, subgraph
from .seed import seed_graph
```

调用示例：
```python
from eda_agent.knowledge_graph import find_causal_path, find_root_causes

# 从 setup_violation 反查所有根因路径
roots = find_root_causes("setup_violation", max_depth=4)
# → [("high_density", ["high_density","congestion","routing_detour","setup_violation"]),
#    ("cts_imbalance", ["cts_imbalance","clock_skew","hold_violation"])]

# 查询两节点间的因果路径
path = find_causal_path("high_density", "setup_violation")
# → ["high_density", "congestion", "routing_detour", "setup_violation"]
```

---

### 关键设计决策

1. **不使用 Neo4j/NetworkX 等外部图库**：用两张 PostgreSQL 表 + Python BFS，保持零新依赖，与现有 DB 栈一致。
2. **图谱与规则并存，不替换 `rules.py`**：通过 `evidence_rule_ids` 字段连接两套系统，渐进迁移。
3. **遵守仓库 JSONB 兼容约定**：`properties`/`conditions`/`evidence_rule_ids` 字段均用 `supports_postgresql_jsonb()` 门控。
4. **migration 编号 `0014`**：继续现有 Alembic 序列，遵守 `ON CONFLICT` 兼容约定。

---

## Q3：知识图谱的使用场景是什么？程序是如何调用的？能否给个例子？

### 核心使用场景：增强推理引擎

目前 `inference/engine.py` 的 `infer()` 流程是**盲式评分**——对所有 6 条规则逐一打分，不知道规则之间的因果关系。知识图谱的作用是让推理引擎**知道"为什么"**，而不只是"什么分数最高"。

---

### 场景一：工程师问「为什么有 setup violation？」

**调用链**（结合现有代码）：

```
工程师 → chat → Planner.run_react_loop()
                    ↓
              infer(run_id=42, symptoms="setup violation WNS=-0.8ns")
                    ↓
         知识图谱: find_root_causes("setup_violation")
                    ↓ 返回:
                    [high_density → congestion → routing_detour → setup_violation]
                    [power_noise → ir_drop → setup_violation]
                    ↓
         推理引擎只评分图谱返回的相关规则，而非全部规则
                    ↓
         返回 hypotheses: [{cause_id: "routing_detour", confidence: "high", ...}]
                    ↓
         Planner 构建回答 + 因果路径说明 + 实验建议
```

**代码层面的具体对接**（改动 `inference/engine.py`）：

```python
# 现有代码（盲式评分所有规则）
for rule in RULES:
    raw_score, evidence, anti_evidence = rule.score(fv)
    ...

# 接入知识图谱后（图谱预筛选）
from eda_agent.knowledge_graph import find_root_causes

# 从症状推断相关根因节点
# symptom_id 由 features 中最显著的异常字段映射得到
symptom_id = "setup_violation" if fv.get("wns_ns", 0) < -0.2 else None
if symptom_id:
    root_candidates = find_root_causes(symptom_id, max_depth=4)
    candidate_rule_ids = {node_id for node_id, _ in root_candidates}
    active_rules = [r for r in RULES if r.id in candidate_rule_ids]
else:
    active_rules = RULES  # 降级为全量评分

for rule in active_rules:
    ...
```

---

### 场景二：PnR Agent 向 LLM 注入因果上下文

当前 `pnr_agent.py` 调用 `infer()` 后，只把 `hypotheses` 传给 LLM。知识图谱可以额外提供**因果路径文本**，让 LLM 给出更有解释性的回答。

```python
# pnr_agent.py 中（现有代码）
infer_result = infer(run_id=task.run_id, symptoms=task.objective)
hypotheses = infer_result.get("hypotheses") or []

# 新增：从知识图谱获取因果链说明
from eda_agent.knowledge_graph import find_causal_path

causal_context = []
for h in hypotheses[:2]:
    cause_id = h.get("cause_id")          # 如 "routing_detour"
    # routing_detour 的上游是 high_density → congestion → routing_detour
    path = find_causal_path("high_density", cause_id)
    if path:
        causal_context.append(" → ".join(path))

# outputs 中增加 causal_chains 字段
outputs = {
    "hypotheses": hypotheses,
    "candidate_experiments": candidate_experiments,
    "causal_chains": causal_context,  # ← 新增
    "note": "PnR analysis active",
}
```

LLM 收到的 tool result 就从只有结论变成了：
> 根因诊断：`routing_detour`（置信度 high）
> 因果链：`high_density → congestion → routing_detour → setup_violation`
> 建议实验：降低 CORE_UTILIZATION 5% 后重跑布局

---

### 场景三：`confirm()` 反馈强化图谱边权重

现有的 `confirm()` 函数已经调用 `update_weights()` 更新规则乘数。知识图谱可以同步更新边的 `weight`：

```python
# inference/engine.py confirm() 中（现有代码）
update_weights(confirmed_cause_id=confirmed_cause_id, top_hypotheses=hypotheses)
save_case(design_name=..., root_cause=root_cause_text, ...)

# 新增：强化确认路径上的边权重
from eda_agent.knowledge_graph import strengthen_edge_weight

# 工程师确认 "routing_detour" 是根因，
# 则 congestion → routing_detour 这条边的置信度上升
strengthen_edge_weight(
    source_id="congestion",
    target_id="routing_detour",
    delta=0.05  # 每次确认增加边权重
)
```

---

### 场景四：Multi-Agent cycle 的共享上下文

```python
# planner.py run_multi_agent_cycle() 中
from eda_agent.knowledge_graph import subgraph

# 注入与当前目标相关的子图
kg_context = subgraph("setup_violation", depth=2)
# 返回: {
#   "nodes": [{"id":"setup_violation",...}, {"id":"routing_detour",...}, ...],
#   "edges": [{"source":"routing_detour","target":"setup_violation","kind":"contributes_to",...}]
# }

task = {
    "task_id": ...,
    "objective": objective,
    "inputs": {
        **(inputs or {}),
        "kg_context": kg_context,   # ← 所有 sub-agent 共享图谱子图
    },
    ...
}
```

---

### 不使用知识图谱 vs 使用知识图谱的对比

| | 当前（无图谱） | 接入知识图谱后 |
|---|---|---|
| 推理过程 | 盲评所有规则，不知道规则间关联 | 从 violation 反向找可能的根因规则子集 |
| LLM 上下文 | 只有「结论：routing_detour 置信度高」 | 有「结论 + 因果链 + 参数节点关系」 |
| Multi-Agent 协作 | 各 agent 独立，输入相同的原始 features | 共享图谱子图，同一因果框架下分析 |
| 工程师反馈 | 只更新规则分数乘数 | 同时强化图谱边权重，图谱随项目积累变精准 |
| 可解释性 | "最可能是 routing_detour" | "high_density 导致 congestion，congestion 导致 routing_detour，进而引发 setup_violation" |

---

## Q4：知识图谱如何从零开始构建？数据来源是什么？

### 从零构建可以按这条主线做：**先有"专家规则种子图"，再用运行数据持续修正权重**。

### 数据来源（按优先级）

1. **现有规则库（首批种子）**
   直接来自 `eda_agent/agent/inference/rules.py`：
   - 根因节点：`routing_detour` / `cts_skew` / `density_saturation`...
   - 证据特征：`wns_ns`、`congestion_hotspot_count`、`utilization_pct`...
   - 修复动作：`ExperimentSuggestion.action/param_hint`

2. **现有结构化运行数据（自动增量）**
   来自 `features.py` 当前读取的表：
   - `timing_summary` / `congestion_hotspots` / `utilization_summary` / `power_summary` / `drc_violations`
   这些不是"知识"，但能作为边权更新证据。

3. **工程师确认反馈（高价值监督信号）**
   来自 `engine.py::confirm()`、`root_cause_inferences`、`case_memory`：
   - "这次真正根因是什么"
   - "哪些实验有效"
   这是图谱质量提升最快的数据源。

4. **流程与决策上下文（可选）**
   `decision_trace` / `stage_outcomes`：补充"在什么阶段、什么条件下某因果更可信"。

---

### 从零构建步骤

1. **定义本体（最小可用）**
   节点：`violation / phenomenon / metric / parameter`
   边：`causes / contributes_to / fixed_by / indicates`

2. **把 rules.py 转成图谱种子**
   - 每条 Rule => 一个"根因/现象节点"
   - Condition feature => 指标节点，连 `indicates` 边
   - ExperimentSuggestion => 参数或动作节点，连 `fixed_by` 边
   这样第一天就能用，不等历史数据。

3. **落库（kg_nodes / kg_edges）并 seed**
   初始化导入一次种子；后续仅 upsert。

4. **接入推理链路**
   在 `infer()` 前做图谱查询（先找候选根因，再评分），不是全量盲评分。

5. **在线学习**
   `confirm()` 后更新：
   - 命中路径边权上调
   - 未命中但高分候选边权下调
   - 有效实验动作与根因关联增强

---

### 一个简化例子

初始种子：
- `high_density --causes--> congestion`
- `congestion --causes--> routing_detour`
- `routing_detour --contributes_to--> setup_violation`
- `routing_detour --fixed_by--> reduce_core_utilization`

某次 run 数据：
- `wns_ns=-0.7`, `congestion_hotspot_count=8`, `utilization_pct=82%`

流程：
1. 图谱反查 `setup_violation` 的上游根因候选：`routing_detour`, `density_saturation`
2. `infer()` 只对相关规则评分
3. 给出建议：`reduce_core_utilization`
4. 工程师确认后 QoR 改善，`confirm()` 触发边权上调
   - `congestion -> routing_detour` +0.05
   - `routing_detour -> setup_violation` +0.05
   - `routing_detour -> reduce_core_utilization` +0.03

结果：图谱从"专家先验"逐步变成"数据+反馈驱动"的知识系统。

---

## Q5：Multi-agent 相比 Single-agent 的优势在哪里？使用场景是什么？

### Single Agent 的局限（当前 Planner 的问题）

看 `planner.py` 的 ReAct 循环，一个 Planner 承担了所有事：
- 理解用户意图
- 选择工具
- 分析 timing / congestion / power / DRC
- 决定是否运行实验
- 生成最终建议

**问题**：EDA 流程的每个子领域知识量巨大。单个 Agent 必须在同一个 context window 里同时处理布局问题、时序问题、signoff 问题——结果是每个方向都分析得不够深，而且 system prompt 越来越长，LLM 表现下降。

---

### Multi-Agent 的三大核心优势

#### 1. 专业深度 vs 宽度

| | Single Agent | Multi-Agent |
|---|---|---|
| PnR 分析 | 泛化工具调用 | PnRAgent：专注 placement/routing，有专用特征提取逻辑 |
| 时序分析 | 同一 LLM 处理 | STAAgent：专注 WNS/TNS/skew，知道 hold vs setup 根因不同 |
| Signoff | 同一 LLM 处理 | SignoffAgent：专注 DRC/IR/power，有独立的判断阈值（utilization ≤85%, power ≤5W） |

从代码看，`signoff_agent.py` 中判断 `signoff_ready` 的逻辑（utilization ≤85%, power ≤5W, no DRC）是与 PnR 分析完全正交的逻辑，不应混在同一个 LLM 调用里。

#### 2. 并行执行

`_dispatch_subagents()` 当前虽然是串行，但架构上支持并行：4 个 sub-agent 分别对同一个 `run_id` 做分析，不存在数据依赖。在真实生产环境中：
- PnR 查 `congestion_hotspots` 表
- STA 查 `timing_summary` 表
- Signoff 查 `utilization_summary + power_summary + drc_violations` 表

这三个查询可以真正并发，而 single agent 只能串行 tool call。

#### 3. 隔离故障域

若 STA 数据库查询失败（timing 表为空），`status="error"` 只影响 STA envelope，不会污染 PnR 的分析结果。Single agent 遇到一个工具调用失败往往会在整个对话中陷入困惑。

---

### 在 eda_agent 中的具体使用场景

#### 场景 A：复合 QoR 问题（最典型）

工程师说："这个 design 跑完后既有 setup violation，又有 DRC，还有功耗超标，怎么办？"

**Single agent**：串行 tool call，先查 timing → 再查 DRC → 再查 power，每步都要等待，且 LLM 上下文被大量数据占满，最终综合建议质量差。

**Multi-agent**：
- PnRAgent 发现 congestion → routing_detour 是 setup violation 根因
- STAAgent 发现 hold violation 同时存在（另一类问题）
- SignoffAgent 发现 power 超标源自过度 buffer 插入
- ExperimentAgent 接收三家分析，综合建议：先降 utilization（同时改善 congestion + DRC），再检查 hold repair

三个问题被同一 cycle 一次处理，决策视图（`decision_view`）给出统一的 `next_action`。

#### 场景 B：HITL Gate 多维判断

当前 `_apply_hitl_gate()` 只看 `experiment.risk_level`，这是 single agent 思维残留。Multi-agent 的优势是把风险判断分散到各 agent：
- SignoffAgent 发现 `drc_hotspots` 非空 → 也应触发审批
- STAAgent 发现 `negative_wns` → 实验可能恶化 setup → 也应升级为 needs_approval

只有多个 agent 独立给出风险信号，汇聚后才能形成可靠的门控。

#### 场景 C：长流程的分段推理

一个完整的 PnR 流程有 synthesis → placement → CTS → routing → signoff 多个阶段，每个阶段的问题性质截然不同。Multi-agent 可以在每个阶段激活不同的专家组合：
- placement 阶段：PnR + Experiment
- CTS 阶段：STA + Experiment
- signoff 阶段：Signoff（全量），PnR/STA 只做辅助

而 single agent 需要在一个 context 里同时记住所有阶段的知识。

---

### 一句话总结

**Single agent 适合简单、单领域的问答（"这条 timing path 为什么 fail？"）；Multi-agent 适合需要跨领域综合判断的场景（"这个 design 能 tapeout 吗？如果不能，从哪里下手？"）**。eda_agent 的调试工作天然是后者——时序、物理、功耗、DRC 往往同时出问题，且根因之间存在真实的因果耦合，这正是 multi-agent 架构的核心价值所在。
