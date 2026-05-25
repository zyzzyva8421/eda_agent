"""PnR sub-agent skeleton."""

from __future__ import annotations

from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


class PnRAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "pnr"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        outputs = {
            "hypotheses": task.inputs.get("hypotheses", []),
            "candidate_experiments": task.inputs.get("candidate_experiments", []),
            "note": "PnR analysis skeleton active",
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
