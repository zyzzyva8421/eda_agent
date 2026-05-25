"""STA sub-agent skeleton."""

from __future__ import annotations

from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


class STAAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "sta"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        outputs = {
            "critical_paths_summary": task.inputs.get("critical_paths_summary", []),
            "constraint_warnings": task.inputs.get("constraint_warnings", []),
            "note": "STA analysis skeleton active",
        }
        return AgentEnvelope.ok(
            task_id=task.task_id,
            agent=self.name,
            objective=task.objective,
            session_id=task.session_id,
            run_id=task.run_id,
            constraints=task.constraints,
            inputs=task.inputs,
            outputs=outputs,
        )
