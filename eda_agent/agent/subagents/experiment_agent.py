"""Experiment sub-agent skeleton."""

from __future__ import annotations

from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


class ExperimentAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "experiment"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        risk_level = str(task.inputs.get("risk_level") or task.constraints.get("risk_level") or "low")
        outputs = {
            "next_action": task.inputs.get("next_action", "propose_experiment"),
            "risk_level": risk_level,
            "requires_approval": risk_level == "high",
            "note": "Experiment planning skeleton active",
        }
        status = "needs_approval" if outputs["requires_approval"] else "ok"
        return AgentEnvelope(
            task_id=task.task_id,
            agent=self.name,
            session_id=task.session_id,
            run_id=task.run_id,
            objective=task.objective,
            constraints=task.constraints,
            inputs=task.inputs,
            outputs=outputs,
            status=status,
        )
