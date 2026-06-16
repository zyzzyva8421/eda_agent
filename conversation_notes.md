# 对话整理（Multi-Agent / 知识图谱）

## 1) 如何让 Multi-agent 成为一个强协作实体？

### 结论
要从“并行独白”升级为“强协作实体”，核心是让各子代理共享上下文并进行综合裁决，而不是只做独立输出拼接。

### 关键改进点
- 流水线上下文传递：PnR → STA → Signoff → Experiment，前一个 agent 的输出进入后一个 agent 输入。
- 共享黑板（shared board）：所有 agent 读写同一结构化上下文。
- 合并逻辑升级：从简单聚合改为矛盾检测、共识评分、置信度融合。
- HITL gate 多维化：不只看 risk_level，还结合 negative_wns、drc_hotspots、signoff_ready、has_error。
- ExperimentAgent 实体化：基于多 agent 综合结论生成实验，而不是仅透传输入字段。
- 历史案例接入：在多代理循环开始前引入 case memory 检索结果作为先验。
- 动态 agent 路由：按 objective 激活必要 agent，失败时支持降级路径。

---

## 2) 如何实现独立图谱建模 / 存储 / 查询模块？

### 结论
可在仓库中新增独立子包 `eda_agent/knowledge_graph/`，形成“建模-存储-查询-种子”闭环，并与现有 `inference`、`planner`、`subagents` 渐进集成。

### 模块建议
- `model.py`：定义 Node / Edge（kind、weight、conditions、evidence_rule_ids）。
- `store.py`：节点边 upsert / read API。
- `query.py`：路径查询、根因反查、修复建议检索、子图抽取。
- `seed.py`：将 `rules.py` 规则映射为初始图谱。

### 存储建议（PostgreSQL）
- 新表：`kg_nodes`、`kg_edges`。
- JSON 字段继续遵循仓库兼容策略：通过 `supports_postgresql_jsonb()` 做 JSONB 门控。
- Alembic 新增迁移（例如 `0014_add_knowledge_graph.py`），并建立必要索引。

### 集成建议
- `infer()` 前先做图谱候选筛选，减少盲评分。
- `pnr_agent.py`/`planner.py` 注入路径/子图作为上下文，增强解释性。
- `confirm()` 后更新边权，形成反馈学习闭环。

---

## 3) 知识图谱的使用场景是什么？程序如何调用？示例？

### 使用场景
- 根因诊断解释增强：不仅输出“哪个根因”，还输出“因果链”。
- 多代理共享认知框架：各 agent 基于同一子图分析，减少结论冲突。
- 反馈学习：工程师确认结果后回写图谱边权与规则关联。

### 程序调用（示意）
- 在 `infer()` 里先调用 `find_root_causes("setup_violation")` 缩小候选规则。
- 在 `pnr_agent.py` 中调用 `find_causal_path()` 生成可解释因果链文本。
- 在 `confirm()` 后调用图谱权重更新逻辑，强化被验证路径。

### 示例
- 输入症状：`WNS=-0.7, congestion hotspots=8, utilization=82%`
- 查询路径：`high_density -> congestion -> routing_detour -> setup_violation`
- 输出建议：优先降低利用率并重跑关键阶段。

---

## 4) 知识图谱如何从零开始构建？数据来源是什么？

### 从零构建路线
1. 先定义最小本体：节点类型（violation/phenomenon/metric/parameter）、边类型（causes/fixed_by/indicates 等）。
2. 用现有 `rules.py` 生成第一版种子图谱（专家先验）。
3. 落库并 seed（`kg_nodes` / `kg_edges`）。
4. 接入 `infer()` 的候选筛选与解释链路。
5. 用 `confirm()` 与 case memory 做在线权重更新。

### 数据来源（优先级）
1. 规则库：`eda_agent/agent/inference/rules.py`（首批种子）。
2. 结构化运行数据：`timing_summary`、`congestion_hotspots`、`utilization_summary`、`power_summary`、`drc_violations`。
3. 工程师确认反馈：`confirm()`、`root_cause_inferences`、`case_memory`。
4. 决策与阶段上下文（可选增强）：`decision_trace`、`stage_outcomes`。

---

## 5) Multi-agent 相比 single-agent 的优势在哪里？使用场景是什么？

### 核心优势
- 专业分工：PnR / STA / Signoff / Experiment 各自深耕，避免单体 agent 认知过载。
- 并行潜力：多个子任务可并发分析，缩短整体决策时间。
- 故障隔离：某个子代理失败不必拖垮全局。
- 更强治理：可做分层门控与风险合成，提升自动执行安全性。
- 更高解释性：最终结论可附带“哪一类 agent 提供了何种证据”。

### 适用场景
- 复合问题：时序、拥塞、功耗、DRC 同时恶化。
- 跨阶段优化：placement / CTS / routing / signoff 联动决策。
- 需要 HITL 审批与可追溯解释的高风险实验。

### 对比总结
- Single-agent：适合单领域、低复杂度、快速问答。
- Multi-agent：适合跨领域、强约束、需要协同裁决的工程问题。

---

## 备注
- 本文件为本轮“上文全部主题对话”的整理版，按问题分节归档，便于后续复用与评审。
