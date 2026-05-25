"""Signoff sub-agent skeleton."""

from __future__ import annotations

from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


class SignoffAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "signoff"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        outputs = {
            "signoff_ready": bool(task.inputs.get("signoff_ready", False)),
            "drc_hotspots": task.inputs.get("drc_hotspots", []),
            "ir_em_risks": task.inputs.get("ir_em_risks", []),
            "note": "Signoff analysis skeleton active",
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
