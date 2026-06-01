# Multi-Agent Role Mapping (v3 对齐草案)

## 1. 目标与范围

本文档用于把 v3 设计中的领域型多代理角色落到当前代码结构，避免“概念一致、实现分叉”。

覆盖范围：
- 角色定义与职责边界
- 角色间消息契约
- 与当前代码文件/接口映射
- 最小可落地的实现顺序（MVP）

不覆盖：
- 大规模训练策略
- UI 交互细节

---

## 2. v3 角色到实现角色映射

v3 文档角色：
- PnR Agent
- STA Agent
- Signoff Agent
- Experiment Agent

实现建议增加编排角色：
- Orchestrator Agent（新增）

### 2.1 角色映射表

| v3 角色 | 实现角色 | 主要职责 | 只读/可执行 | 主要输出 |
|---|---|---|---|---|
| PnR Agent | `PnRAgent` | 拥塞/布局/CTS/route 原因分析与参数建议 | 读+建议 | `hypotheses` + `candidate_experiments` |
| STA Agent | `STAAgent` | 时序路径诊断、约束异常识别、时序目标拆解 | 读+建议 | `timing_diagnosis` + `target_decomposition` |
| Signoff Agent | `SignoffAgent` | DRC/IR/EM 风险判断、signoff readiness | 读+建议 | `signoff_risk_report` |
| Experiment Agent | `ExperimentAgent` | 计划实验、下发执行、比较前后 run | 可执行 | `experiment_result` + `delta_metrics` |
| (新增) | `OrchestratorAgent` | 路由请求、仲裁冲突、收敛判定、HITL 门控 | 可执行(调度) | `next_action` + `session_decision` |

说明：
- 只有 `ExperimentAgent` 能触发执行工具（run_eda_stage / run_eda_flow）。
- 其他领域 agent 只能给建议，不直接跑流。

---

## 3. 当前代码映射（文件/接口级）

### 3.1 OrchestratorAgent

建议落位：
- `eda_agent/agent/planner.py`

映射：
- `Planner.run(...)` 作为 orchestrator 主循环入口
- 负责：
  - 选择子 agent
  - 合并子 agent 输出
  - 触发 HITL 决策（高风险动作）
  - 写入决策轨迹

### 3.2 PnRAgent

建议落位：
- `eda_agent/agent/subagents/pnr_agent.py`（新增）

复用接口：
- `eda_agent/agent/tools.py` 中查询类工具（timing/congestion/utilization）
- `eda_agent/agent/inference/engine.py` 规则推理
- `eda_agent/agent/param_mapper.py` 参数空间

### 3.3 STAAgent

建议落位：
- `eda_agent/agent/subagents/sta_agent.py`（新增）

复用接口：
- `query_timing` / `_query_timing`
- `_check_ppa_target`
- 规则引擎中 timing 相关特征

### 3.4 SignoffAgent

建议落位：
- `eda_agent/agent/subagents/signoff_agent.py`（新增）

复用接口：
- DRC / power / utilization 查询工具
- signoff stage 的结果摘要

### 3.5 ExperimentAgent

建议落位：
- `eda_agent/agent/subagents/experiment_agent.py`（新增）
- `eda_agent/agent/optimization_loop.py`（复用）

复用接口：
- `optimize_with_inference`
- `run_eda_stage` / `run_eda_flow`
- `run_context` 注入（session_id/stage_seq/parent_run_id）

---

## 4. 角色间消息契约（MVP）

所有 agent 间交换统一 envelope，避免耦合内部字段。

```json
{
  "task_id": "uuid",
  "session_id": 123,
  "run_id": 456,
  "agent": "pnr|sta|signoff|experiment|orchestrator",
  "objective": "WNS >= -0.1 and overflow_h_pct <= 2.0",
  "constraints": {
    "max_runtime_sec": 7200,
    "risk_level": "low|medium|high",
    "require_human_approval": false
  },
  "inputs": {},
  "outputs": {},
  "status": "ok|error|needs_approval",
  "error": ""
}
```

### 4.1 关键输出字段约束

- `PnRAgent.outputs`
  - `hypotheses`: root cause 列表（带 score）
  - `candidate_experiments`: 参数建议列表（含 risk）

- `STAAgent.outputs`
  - `critical_paths_summary`
  - `slack_distribution`
  - `constraint_warnings`

- `SignoffAgent.outputs`
  - `drc_hotspots`
  - `ir_em_risks`
  - `signoff_ready`: bool

- `ExperimentAgent.outputs`
  - `new_run_id`
  - `delta_metrics`
  - `target_met`

---

## 5. 决策与门控规则（HITL）

默认自动执行条件：
- 风险等级为 low
- 不涉及 floorplan 几何修改
- 不涉及时序例外（false path/multicycle）写入

必须人工确认条件：
- 风险等级 high
- 动作命中 guardrails 黑名单
- 连续两轮 QoR 退化

建议复用：
- `eda_agent/agent/guardrails.py`
- `decision_trace` 的 structured reason 持久化

---

## 6. VM Innovus 测试映射到角色（供后续测试规范复用）

- Smoke（单 stage）
  - Orchestrator -> PnR -> Experiment
  - 验证：能创建 session，能执行 1 次 stage，指标可入库

- Standard（迭代修复）
  - Orchestrator -> PnR/STA -> Experiment -> Validation
  - 验证：至少完成 1 次 root-cause -> experiment -> re-run

- Nightly（多 case）
  - 多 session 并发，验证稳定性和可追溯性

注：完整 VM 用例分层/门槛将单独写入测试规范文档。

---

## 7. 实施顺序（建议）

### M1: 协议与骨架
- 新增 `subagents/` 目录与 4 个 agent 类
- 定义统一消息 envelope
- Orchestrator 仅做顺序调用，不做复杂仲裁

### M2: 执行闭环
- 接入 `ExperimentAgent` 到 `optimize_with_inference`
- 打通 `decision_trace` 字段与 run_context lineage

### M3: 风险门控
- 接入 guardrails + HITL 条件
- 增加 `needs_approval` 路径

### M4: VM 回归
- 把 smoke/standard/nightly 映射到 pytest marker
- 固化失败归因模板（log 摘要 + rule id + stage_outcome）

---

## 8. 验收标准

满足以下条件视为“与 v3 多代理设计对齐”：
- 角色分工至少覆盖 PnR/STA/Signoff/Experiment
- 执行权限只在 ExperimentAgent
- 所有跨角色决策可在 session trace 回放
- 高风险动作具备 HITL 门控
- VM Innovus 至少有 smoke + standard 两层自动化回归

---

## 9. VM Innovus 用例搭建草案（可直接落地）

### 9.1 用例清单文件（建议新增）

建议新增：`tests/integration/vm_innovus_cases.yaml`

示例：

```yaml
version: 1
default_timeout_sec: 10800

cases:
  - case_id: innovus_aes_smoke_place
    tier: smoke
    backend: innovus
    design_name: aes
    design_config: /home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/configs/aes.mk
    pdk: tsmc18
    stages: [place]
    target_spec: "WNS >= -0.5"
    max_iterations: 1
    require_hitl: false

  - case_id: innovus_aes_standard_iterative
    tier: standard
    backend: innovus
    design_name: aes
    design_config: /home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/configs/aes.mk
    pdk: tsmc18
    stages: [place]
    target_spec: "WNS >= -0.1 and overflow_h_pct <= 2.0"
    max_iterations: 3
    require_hitl: false

  - case_id: innovus_gcd_nightly_multistage
    tier: nightly
    backend: innovus
    design_name: gcd
    design_config: /home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/configs/gcd.mk
    pdk: tsmc18
    stages: [place, cts, route]
    target_spec: "WNS >= -0.2 and overflow_h_pct <= 3.0"
    max_iterations: 5
    require_hitl: true
```

### 9.2 pytest 分层标记（建议）

- `@pytest.mark.vm_innovus`
- `@pytest.mark.smoke`
- `@pytest.mark.standard`
- `@pytest.mark.nightly`
- `@pytest.mark.hitl`（需要人工批准路径）

建议在 `pytest.ini` 增加 marker 声明，避免 UnknownMarkWarning。

### 9.3 执行入口建议

- 新增脚本：`scripts/run_vm_innovus_suite.py`
- 功能：
  - 读取 `vm_innovus_cases.yaml`
  - 为每个 case 构造 tool call（优先 `optimize_with_inference`）
  - 统一注入 `session_id` / `run_context`
  - 写回执行摘要（session_id, run_ids, status, target_met）

### 9.4 最小判定规则

每个 case 都应校验：

1. 执行链路
- 能创建/复用 `flow_session`
- 至少产生一个 `runs` 记录
- `stage_outcomes` 与 `decision_trace` 非空（迭代 case）

2. 指标链路
- timing / congestion 至少一类指标成功入库
- `target_spec` 有可计算结果（true/false）

3. 可追溯性
- `parent_run_id` / `stage_seq` 连续
- `llm_reason_structured` 有核心字段（kind/source 或 equivalent）

### 9.5 失败归因模板（建议）

每个失败 case 输出统一 JSON：

```json
{
  "case_id": "innovus_aes_standard_iterative",
  "session_id": 123,
  "failed_stage": "place",
  "run_id": 456,
  "root_cause_inference_id": 42,
  "reason": "target_not_met|backend_error|guardrail_blocked|timeout",
  "log_tail": "...last 120 lines...",
  "suggested_next_action": "reduce_density_and_rerun"
}
```

---

## 10. 代码改造任务分解（函数级）

### 10.1 新增目录与类

- `eda_agent/agent/subagents/base.py`
  - `class AgentEnvelope`
  - `class BaseSubAgent`

- `eda_agent/agent/subagents/pnr_agent.py`
  - `def analyze_pnr(...) -> AgentEnvelope`

- `eda_agent/agent/subagents/sta_agent.py`
  - `def analyze_timing(...) -> AgentEnvelope`

- `eda_agent/agent/subagents/signoff_agent.py`
  - `def analyze_signoff(...) -> AgentEnvelope`

- `eda_agent/agent/subagents/experiment_agent.py`
  - `def execute_experiment(...) -> AgentEnvelope`

### 10.2 Orchestrator 改造

- 文件：`eda_agent/agent/planner.py`
- 新增方法建议：
  - `def _dispatch_subagents(...)`
  - `def _merge_agent_outputs(...)`
  - `def _apply_hitl_gate(...)`

### 10.3 工具层改造

- 文件：`eda_agent/agent/tools.py`
- 建议新增 tool：
  - `run_multi_agent_cycle`
  - 入参：`run_id, target_spec, backend, stage, design_name, design_config, pdk, max_iterations`
  - 内部调用 orchestrator，而非直连单个子 agent

---

## 11. 里程碑与门禁

### M1（架构可运行）
- 子 agent 骨架 + Orchestrator 路由可运行
- 单 case smoke 通过

### M2（闭环可追溯）
- `decision_trace` 能区分 agent 来源
- `session trace` 能回放多 agent 决策

### M3（HITL 生效）
- 高风险动作全部进入 `needs_approval`
- 拒绝后不会触发执行工具

### M4（VM 稳定）
- standard 套件连续 3 次全绿
- nightly 套件连续 7 天无新增高优先级失败
