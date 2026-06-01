"""PnR sub-agent skeleton."""

from __future__ import annotations

from typing import Any

from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


class PnRAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "pnr"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        hypotheses: list[dict[str, Any]] = []
        candidate_experiments: list[dict[str, Any]] = []

        if task.run_id is not None:
            from eda_agent.agent.inference.engine import infer

            infer_result = infer(run_id=task.run_id, symptoms=task.objective)
            hypotheses = infer_result.get("hypotheses") or []

            for h in hypotheses[:3]:
                if not isinstance(h, dict):
                    continue
                exps = h.get("experiments") or []
                if not isinstance(exps, list):
                    continue
                for exp in exps[:2]:
                    if not isinstance(exp, dict):
                        continue
                    candidate_experiments.append(
                        {
                            "cause_id": h.get("cause_id", ""),
                            "display_name": h.get("display_name", ""),
                            "action": exp.get("action", ""),
                            "risk": exp.get("risk", "unknown"),
                            "param_hint": exp.get("param_hint", {}),
                        }
                    )

        outputs = {
            "hypotheses": hypotheses or task.inputs.get("hypotheses", []),
            "candidate_experiments": (
                candidate_experiments or task.inputs.get("candidate_experiments", [])
            ),
            "note": "PnR analysis active",
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
