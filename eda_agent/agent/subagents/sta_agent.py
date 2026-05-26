"""STA sub-agent skeleton."""

from __future__ import annotations

from eda_agent.agent.services import AgentQueryService
from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


_QUERY_SERVICE = AgentQueryService()


class STAAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "sta"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        critical_paths_summary = task.inputs.get("critical_paths_summary", [])
        constraint_warnings: list[str] = list(task.inputs.get("constraint_warnings", []))

        if task.run_id is not None:
            design_name = str(task.inputs.get("design_name") or "")
            stage = task.inputs.get("stage")
            timing = _QUERY_SERVICE.query_timing(
                design_name=design_name,
                stage=stage if isinstance(stage, str) else None,
                run_id=task.run_id,
                limit=5,
            )

            summary = timing.get("summary") or []
            paths = timing.get("paths") or []
            critical_paths_summary = paths[:5]

            if summary:
                s0 = summary[0]
                if (s0.get("hold_violations") or 0) > 0:
                    constraint_warnings.append("hold_violations_detected")
                if (s0.get("setup_violations") or 0) > 0:
                    constraint_warnings.append("setup_violations_detected")
                if (s0.get("wns_ns") or 0) < 0:
                    constraint_warnings.append("negative_wns")

        outputs = {
            "critical_paths_summary": critical_paths_summary,
            "constraint_warnings": sorted(set(constraint_warnings)),
            "note": "STA analysis active",
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
