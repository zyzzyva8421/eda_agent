"""Signoff sub-agent skeleton."""

from __future__ import annotations

from eda_agent.agent.services import AgentQueryService
from eda_agent.agent.subagents.base import AgentEnvelope, BaseSubAgent


_QUERY_SERVICE = AgentQueryService()


class SignoffAgent(BaseSubAgent):
    @property
    def name(self) -> str:
        return "signoff"

    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        signoff_ready = bool(task.inputs.get("signoff_ready", False))
        drc_hotspots = task.inputs.get("drc_hotspots", [])
        ir_em_risks = task.inputs.get("ir_em_risks", [])
        power_summary = []
        utilization_summary = []

        if task.run_id is not None:
            design_name = str(task.inputs.get("design_name") or "")
            stage = task.inputs.get("stage")
            stage_val = stage if isinstance(stage, str) else None

            utilization_summary = _QUERY_SERVICE.query_utilization(
                design_name=design_name,
                stage=stage_val,
                run_id=task.run_id,
                limit=1,
            )
            power_summary = _QUERY_SERVICE.query_power(
                design_name=design_name,
                stage=stage_val,
                run_id=task.run_id,
                limit=1,
            )

            util_ok = True
            if utilization_summary:
                util_pct = utilization_summary[0].get("utilization_pct")
                if isinstance(util_pct, (int, float)):
                    util_ok = util_pct <= 85.0

            power_ok = True
            if power_summary:
                total_power = power_summary[0].get("total_power_w")
                if isinstance(total_power, (int, float)):
                    power_ok = total_power <= 5.0

            signoff_ready = util_ok and power_ok and not drc_hotspots and not ir_em_risks

        outputs = {
            "signoff_ready": signoff_ready,
            "drc_hotspots": drc_hotspots,
            "ir_em_risks": ir_em_risks,
            "power_summary": power_summary,
            "utilization_summary": utilization_summary,
            "note": "Signoff analysis active",
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
