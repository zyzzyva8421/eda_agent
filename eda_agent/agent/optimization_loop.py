"""Iterative optimisation loop: 推理 → 决策 → 执行 → 验证 → 再推理.

Orchestrates Phase A (rule-based inference) and Phase B (feedback learning)
into a closed loop so that each tuning iteration is guided by the root-cause
hypothesis from the previous run.

Typical usage::

    from eda_agent.agent.optimization_loop import OptimizationLoop

    loop = OptimizationLoop(session_id=42)
    result = loop.orchestrate(
        run_id=101,
        target_spec="WNS >= -0.1 and overflow_h_pct <= 2.0",
        backend="innovus",
        stage="place",
        design_name="aes",
        design_config="/cfg/aes.mk",
        pdk="sky130hd",
    )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from eda_agent.agent.inference.engine import infer, confirm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class IterationRecord:
    """Snapshot of one full loop iteration."""

    iteration: int
    inference_id: int
    cause_id: str
    cause_display_name: str
    experiment_action: str
    experiment_risk: str
    params_applied: dict[str, Any]
    new_run_id: int | None
    new_run_status: str
    converged: bool
    target_met: bool
    score_dropped: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "inference_id": self.inference_id,
            "cause_id": self.cause_id,
            "cause_display_name": self.cause_display_name,
            "experiment_action": self.experiment_action,
            "experiment_risk": self.experiment_risk,
            "params_applied": self.params_applied,
            "new_run_id": self.new_run_id,
            "new_run_status": self.new_run_status,
            "converged": self.converged,
            "target_met": self.target_met,
            "score_dropped": self.score_dropped,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class OptimizationLoop:
    """Closed-loop optimisation driven by the Phase A inference engine.

    Each iteration::

        infer_current_run → pick_experiment → apply_and_run → verify → converge?
                                                                    │
                                                            (yes)  │  (no)
                                                                    │
                                                               done  └──→ infer_new_run
    """

    def __init__(
        self,
        session_id: int,
        max_iterations: int = 5,
        convergence_score_threshold: float = 0.35,
    ) -> None:
        self.session_id = session_id
        self.max_iterations = max_iterations
        self.convergence_score_threshold = convergence_score_threshold
        self.history: list[IterationRecord] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def orchestrate(
        self,
        run_id: int,
        target_spec: str,
        *,
        backend: str,
        stage: str,
        design_name: str,
        design_config: str,
        pdk: str,
        base_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the full infer → experiment → run → verify → re-infer loop.

        Parameters
        ----------
        run_id:
            DB id of the *first* (baseline) run to diagnose.
        target_spec:
            Natural-language PPA target (same format as
            :func:`~tools._check_ppa_target`).
        backend, stage, design_name, design_config, pdk:
            Passed through to every ``_run_eda_stage`` call.
        base_params:
            Fixed parameters carried through every iteration (merged with
            experiment suggestions).

        Returns
        -------
        {
            "converged": bool,
            "iterations_run": int,
            "target_spec": str,
            "session_id": int,
            "inference_cycle": [
                {"iteration": 1, "cause_id": "...", "experiment_action": "...", ...},
            ],
            "final_inference": {...} | None,
        }
        """
        if base_params is None:
            base_params = {}

        current_run_id = run_id
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            logger.info(
                "OptimizationLoop iteration %d/%d (run_id=%s)",
                iteration, self.max_iterations, current_run_id,
            )

            # ── Step 1: Phase A inference ──────────────────────────────────
            inference_result = infer(run_id=current_run_id, symptoms=target_spec)
            inference_id = inference_result.get("inference_id", -1)
            hypotheses = inference_result.get("hypotheses") or []

            # ── Step 2: pick the best experiment from top hypothesis ───────
            experiment = self._select_experiment(hypotheses)
            if experiment is None:
                logger.info(
                    "No actionable experiment from top hypothesis – stopping loop"
                )
                self._record_iteration(
                    iteration=iteration,
                    inference_result=inference_result,
                    experiment=None,
                    experiment_params={},
                    new_run_id=None,
                    new_run_status="skipped",
                    converged=False,
                    target_met=False,
                    score_dropped=False,
                )
                break

            # ── Step 3: apply experiment → execute ─────────────────────────
            experiment_params = self._experiment_to_params(experiment)
            merged_params = {**base_params, **experiment_params}

            new_run_result = self._execute_stage(
                backend=backend,
                stage=stage,
                design_name=design_name,
                design_config=design_config,
                pdk=pdk,
                params=merged_params,
                prev_run_id=current_run_id,
                iteration=iteration,
                inference_id=inference_id,
            )
            new_run_id = new_run_result.get("run_id")
            new_run_status = new_run_result.get("status", "failed")

            # ── Step 4: verify (re-infer on the new run) ───────────────────
            score_dropped = False
            if new_run_id is not None and new_run_status == "success":
                verify_result = infer(
                    run_id=new_run_id,
                    symptoms=(
                        f"after experiment '{experiment['action']}': {target_spec}"
                    ),
                )
                verify_hypotheses = verify_result.get("hypotheses") or []
                score_dropped = self._score_dropped_below_threshold(
                    verify_hypotheses, self.convergence_score_threshold
                )
            else:
                verify_result = None
                score_dropped = False

            # ── Step 5: check convergence ──────────────────────────────────
            target_met = self._check_target(
                new_run_id, target_spec
            ) if new_run_id and new_run_status == "success" else False

            # Convergence: target met OR inference score dropped significantly
            # (meaning the root cause was addressed)
            converged = target_met or score_dropped

            # ── Step 6: record iteration ───────────────────────────────────
            self._record_iteration(
                iteration=iteration,
                inference_result=inference_result,
                experiment=experiment,
                experiment_params=experiment_params,
                new_run_id=new_run_id,
                new_run_status=new_run_status,
                converged=converged,
                target_met=target_met,
                score_dropped=score_dropped,
            )

            if converged:
                logger.info(
                    "OptimizationLoop converged at iteration %d "
                    "(target_met=%s, score_dropped=%s)",
                    iteration, target_met, score_dropped,
                )
                # Phase B: record the successful experiment as confirmed
                if inference_id > 0:
                    confirm(inference_id, experiment["cause_id"])
                break

            # Next iteration: use the new run as baseline
            if new_run_id is not None:
                current_run_id = new_run_id

        return {
            "converged": any(r.converged for r in self.history),
            "iterations_run": len(self.history),
            "target_spec": target_spec,
            "session_id": self.session_id,
            "inference_cycle": [r.to_dict() for r in self.history],
            "final_inference": infer(
                run_id=current_run_id, symptoms=target_spec
            ) if self.history and not self.history[-1].converged else None,
        }

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    @staticmethod
    def _select_experiment(
        hypotheses: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Pick the best experiment from the top hypothesis.

        Prefers low-risk experiments; falls back to any risk level
        (same strategy as ``_build_next_action`` in engine.py).
        """
        if not hypotheses:
            return None
        top = hypotheses[0]
        experiments = top.get("experiments") or []
        if not experiments:
            return None

        # Prefer low risk
        for exp in experiments:
            if exp.get("risk") == "low":
                return {
                    "cause_id": top["cause_id"],
                    "display_name": top.get("display_name", ""),
                    "action": exp.get("action", ""),
                    "risk": "low",
                    "param_hint": exp.get("param_hint", {}),
                }

        # Fallback to any risk
        first = experiments[0]
        return {
            "cause_id": top["cause_id"],
            "display_name": top.get("display_name", ""),
            "action": first.get("action", ""),
            "risk": first.get("risk", "unknown"),
            "param_hint": first.get("param_hint", {}),
        }

    @staticmethod
    def _experiment_to_params(experiment: dict[str, Any]) -> dict[str, Any]:
        """Convert an experiment's ``param_hint`` into runnable EDA parameters."""
        param_hint = experiment.get("param_hint", {})
        if not isinstance(param_hint, dict):
            return {}

        # param_hint values come as strings; convert numeric-looking ones
        params: dict[str, Any] = {}
        for key, value in param_hint.items():
            if isinstance(value, str):
                # Try numeric conversion for Innovus-style params
                try:
                    if "." in value:
                        params[key] = float(value)
                    else:
                        params[key] = int(value)
                except (ValueError, TypeError):
                    params[key] = value
            else:
                params[key] = value
        return params

    @staticmethod
    def _score_dropped_below_threshold(
        hypotheses: list[dict[str, Any]],
        threshold: float,
    ) -> bool:
        """Return True if the top hypothesis score is below *threshold*.

        A score drop below ``convergence_score_threshold`` (default 0.35)
        means the rule engine no longer considers this a significant issue,
        i.e. the root cause has been mitigated.
        """
        if not hypotheses:
            return True  # no fired rules = nothing significant remaining
        top_score = hypotheses[0].get("score", 0.0)
        return float(top_score) < threshold

    # ------------------------------------------------------------------
    # Execution & queries (lazy-imported to avoid circular deps)
    # ------------------------------------------------------------------

    def _execute_stage(
        self,
        backend: str,
        stage: str,
        design_name: str,
        design_config: str,
        pdk: str,
        params: dict[str, Any],
        prev_run_id: int,
        iteration: int,
        inference_id: int,
    ) -> dict[str, Any]:
        """Run one EDA stage through the tools module.

        Wraps the private ``_run_eda_stage`` with correct run_context for
        session tracking.
        """
        from eda_agent.agent.tools import _run_eda_stage as run_stage  # noqa: PLC0415

        result = run_stage(
            backend=backend,
            stage=stage,
            design_name=design_name,
            design_config=design_config,
            pdk=pdk,
            params=params,
            run_context={
                "session_id": self.session_id,
                "stage_seq": iteration,
                "variant_tag": f"opt_iter_{iteration}",
                "rerun_reason": (
                    f"optimization_loop iteration {iteration} "
                    f"inference_id={inference_id}"
                ),
                "is_baseline": iteration == 1,
                "is_selected": False,
                "parent_run_id": prev_run_id,
                "root_cause_inference_id": inference_id,
            },
        )
        return result

    def _check_target(
        self, run_id: int, target_spec: str
    ) -> bool:
        """Evaluate PPA target against the run's queryable metrics.

        Uses ``_query_timing`` and ``_query_congestion_summary`` internally.
        """
        from eda_agent.agent.tools import (  # noqa: PLC0415
            _query_timing,
            _query_congestion_summary,
            _check_ppa_target,
        )

        try:
            timing = _query_timing(design_name="", stage="", run_id=run_id, limit=1)
            congestion = _query_congestion_summary(run_id)
            return _check_ppa_target(timing, target_spec, congestion_summary=congestion)
        except Exception:
            logger.warning(
                "Target check failed for run_id=%s; assuming not met", run_id,
                exc_info=True,
            )
            return False

    def _record_iteration(
        self,
        iteration: int,
        inference_result: dict[str, Any],
        experiment: dict[str, Any] | None,
        experiment_params: dict[str, Any],
        new_run_id: int | None,
        new_run_status: str,
        converged: bool,
        target_met: bool,
        score_dropped: bool,
    ) -> None:
        """Append an iteration record and persist a decision trace row when
        we have a valid transition (old run → new run via experiment)."""
        hypotheses = inference_result.get("hypotheses") or []
        top = hypotheses[0] if hypotheses else {}
        cause_id = top.get("cause_id", "")
        cause_name = top.get("display_name", "")
        exp_action = experiment["action"] if experiment else ""
        exp_risk = experiment["risk"] if experiment else ""

        rec = IterationRecord(
            iteration=iteration,
            inference_id=inference_result.get("inference_id", -1),
            cause_id=cause_id,
            cause_display_name=cause_name,
            experiment_action=exp_action,
            experiment_risk=exp_risk,
            params_applied=experiment_params,
            new_run_id=new_run_id,
            new_run_status=new_run_status,
            converged=converged,
            target_met=target_met,
            score_dropped=score_dropped,
        )
        self.history.append(rec)

        # Persist decision trace when we have a valid run transition
        if (
            experiment is not None
            and new_run_id is not None
            and iteration > 0
        ):
            try:
                from eda_agent.agent.tools import (  # noqa: PLC0415
                    _record_decision_trace,
                )
                _record_decision_trace(
                    session_id=self.session_id,
                    source_run_id=inference_result.get("run_id") or 0,
                    target_run_id=new_run_id,
                    llm_reason=(
                        f"OptimizationLoop iteration {iteration}: "
                        f"hypothesis={cause_name}, experiment={exp_action}"
                    ),
                    llm_reason_structured={
                        "iteration": iteration,
                        "cause_id": cause_id,
                        "cause_display_name": cause_name,
                        "experiment_action": exp_action,
                        "experiment_risk": exp_risk,
                        "converged": converged,
                    },
                    inference_id=inference_result.get("inference_id"),
                    case_id=None,
                    rule_id=cause_id or None,
                )
            except Exception:
                logger.warning(
                    "Failed to persist decision_trace for iteration %d", iteration,
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Convenience wrapper (for the tool dispatch table)
# ---------------------------------------------------------------------------


def optimize_with_inference(
    run_id: int,
    target_spec: str,
    *,
    backend: str,
    stage: str,
    design_name: str,
    design_config: str,
    pdk: str,
    max_iterations: int = 5,
    session_id: int | None = None,
) -> dict[str, Any]:
    """Create an optimisation session and run the loop.

    If *session_id* is omitted, a new flow session is created automatically.

    This is the entry point exposed via ``TOOL_SCHEMAS`` so the LLM can invoke
    the full inference-guided optimisation cycle in a single tool call.
    """
    from eda_agent.agent.tools import _create_flow_session  # noqa: PLC0415
    from eda_agent.db.session import get_db  # noqa: PLC0415

    # Resolve the design id so we can create a flow session
    from sqlalchemy import text  # noqa: PLC0415

    if session_id is None:
        # Build a minimal DesignSpec from the tool arguments
        from pathlib import Path  # noqa: PLC0415
        from eda_agent.backends.base import DesignSpec  # noqa: PLC0415

        design = DesignSpec(
            name=design_name,
            config_path=Path(design_config),
            pdk=pdk,
        )
        session_id = _create_flow_session(
            design,
            objective="optimize_with_inference",
            notes=f"inference-guided: {target_spec}",
        )

    loop = OptimizationLoop(
        session_id=session_id,
        max_iterations=max_iterations,
    )
    result = loop.orchestrate(
        run_id=run_id,
        target_spec=target_spec,
        backend=backend,
        stage=stage,
        design_name=design_name,
        design_config=design_config,
        pdk=pdk,
    )
    result["session_id"] = session_id
    return result
