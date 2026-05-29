"""Root Cause Inference Engine – orchestration layer.

Public API::

    result = infer(run_id, symptoms="wns is -0.5 ns, many congestion hotspots")
    # result["inference_id"]  → int (DB record id)
    # result["hypotheses"]    → list[dict], ranked by score
    # result["summary"]       → human-readable one-liner
    # result["next_action"]   → recommended first experiment

    confirm(inference_id=42, confirmed_cause_id="routing_detour")
    # updates root_cause_inferences.chosen_cause
    # creates a case_memory record for future retrieval
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from eda_agent.db.session import get_db, is_postgresql

from .features import FeatureVector, extract_features
from .rules import RULE_BY_ID, RULES
from .weights import get_multipliers, update_weights

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLDS = {"high": 0.65, "medium": 0.35}


def _score_to_confidence(score: float) -> str:
    if score >= _CONFIDENCE_THRESHOLDS["high"]:
        return "high"
    if score >= _CONFIDENCE_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def _build_summary(hypotheses: list[dict]) -> str:
    if not hypotheses:
        return "No significant root cause identified from available data."
    top = hypotheses[0]
    conf = top["confidence"]
    name = top["display_name"]
    score = top["score"]
    if len(hypotheses) > 1:
        second = hypotheses[1]["display_name"]
        return (
            f"最可能的根因是「{name}」(置信度 {conf}, score={score:.2f})。"
            f"次要候选：「{second}」。"
        )
    return f"最可能的根因是「{name}」(置信度 {conf}, score={score:.2f})。"


def _build_next_action(hypotheses: list[dict]) -> str:
    if not hypotheses:
        return "建议先检查 timing report 和 congestion map，收集更多数据。"
    exps = hypotheses[0].get("experiments", [])
    low_risk = [e for e in exps if e.get("risk") == "low"]
    first = (low_risk or exps or [None])[0]
    if first is None:
        return "暂无具体实验建议，请参考 symptoms 手动分析。"
    hint = first.get("param_hint", {})
    hint_str = f"（参数参考：{hint}）" if hint else ""
    return f"建议优先执行：{first['action']} {hint_str}"


def _save_inference(
    run_id: int,
    symptoms: str,
    features: FeatureVector,
    hypotheses: list[dict],
) -> int:
    """Insert a root_cause_inferences row and return its id."""
    try:
        _jc = "::jsonb" if is_postgresql() else ""
        with get_db() as db:
            row = db.execute(
                text(
                    f"""
                    INSERT INTO root_cause_inferences
                        (run_id, symptoms, features, hypotheses)
                    VALUES
                        (:run_id, :symptoms, :features{_jc}, :hypotheses{_jc})
                    RETURNING id
                    """
                ),
                {
                    "run_id": run_id,
                    "symptoms": symptoms,
                    "features": json.dumps(features, default=str),
                    "hypotheses": json.dumps(hypotheses, default=str),
                },
            ).first()
            return int(row[0])
    except Exception:
        logger.warning("Could not persist inference to DB", exc_info=True)
        return -1


# ── Public API ────────────────────────────────────────────────────────────────

def infer(run_id: int, symptoms: str = "") -> dict:
    """Run the rule engine against *run_id* and return a ranked hypothesis report.

    Parameters
    ----------
    run_id:   DB run id (runs.id) to diagnose.
    symptoms: Optional free-text description of observed problems (used for
              context and stored in the DB record; does not affect scoring).

    Returns
    -------
    {
        "inference_id": int,
        "run_id": int,
        "features": FeatureVector,
        "hypotheses": [
            {
                "rank": 1,
                "cause_id": str,
                "display_name": str,
                "description": str,
                "score": float,
                "confidence": "high"|"medium"|"low",
                "evidence": [...],
                "anti_evidence": [...],
                "experiments": [...]
            },
            ...
        ],
        "summary": str,
        "next_action": str,
    }
    """
    fv = extract_features(run_id)

    # Load per-rule multipliers (Phase B feedback weights)
    multipliers = get_multipliers()

    # Score every rule and apply multiplier
    fired: list[tuple[float, float, list, list, "Rule"]] = []
    for rule in RULES:
        raw_score, evidence, anti_evidence = rule.score(fv)
        mult = multipliers.get(rule.id, 1.0)
        adjusted = min(1.0, raw_score * mult)  # cap at 1.0 to keep confidence thresholds stable
        if adjusted >= rule.min_score:
            fired.append((adjusted, raw_score, evidence, anti_evidence, rule))

    # Sort descending by adjusted score
    fired.sort(key=lambda t: t[0], reverse=True)

    # Build hypothesis list (top 3)
    hypotheses: list[dict] = []
    for rank, (adj_score, raw_score, evidence, anti_evidence, rule) in enumerate(fired[:3], start=1):
        mult = multipliers.get(rule.id, 1.0)
        hypotheses.append(
            {
                "rank": rank,
                "cause_id": rule.id,
                "display_name": rule.display_name,
                "description": rule.description,
                "score": round(adj_score, 4),
                "raw_score": round(raw_score, 4),
                "multiplier": round(mult, 4),
                "confidence": _score_to_confidence(adj_score),
                "evidence": evidence,
                "anti_evidence": anti_evidence,
                "experiments": [e.to_dict() for e in rule.experiments],
            }
        )

    summary = _build_summary(hypotheses)
    next_action = _build_next_action(hypotheses)

    inference_id = _save_inference(run_id, symptoms, dict(fv), hypotheses)

    return {
        "inference_id": inference_id,
        "run_id": run_id,
        "features": dict(fv),
        "hypotheses": hypotheses,
        "summary": summary,
        "next_action": next_action,
    }


def confirm(inference_id: int, confirmed_cause_id: str) -> dict:
    """Record the engineer's confirmed root cause and upsert a case_memory entry.

    Parameters
    ----------
    inference_id:        Row id from root_cause_inferences.
    confirmed_cause_id:  One of the ``cause_id`` values from the hypothesis list
                         (or a free-text string if none matched).

    Returns
    -------
    {"status": "confirmed", "inference_id": ..., "case_id": ...}
    """
    case_id: int = -1
    try:
        with get_db() as db:
            # Mark the chosen cause
            db.execute(
                text(
                    """
                    UPDATE root_cause_inferences
                    SET chosen_cause = :cause,
                        confirmed_at = :now
                    WHERE id = :id
                    """
                ),
                {
                    "cause": confirmed_cause_id,
                    "now": datetime.now(timezone.utc).isoformat(),
                    "id": inference_id,
                },
            )

            # Fetch the full record so we can build a case_memory entry
            rec = db.execute(
                text(
                    "SELECT run_id, symptoms, hypotheses FROM root_cause_inferences WHERE id = :id"
                ),
                {"id": inference_id},
            ).mappings().first()

        if rec:
            run_id = rec["run_id"]
            symptoms = rec["symptoms"] or ""
            hypotheses = rec["hypotheses"] or []

            # Find the chosen hypothesis for action suggestions
            chosen_hyp = next(
                (h for h in hypotheses if h.get("cause_id") == confirmed_cause_id),
                None,
            )
            actions = (
                [e["action"] for e in chosen_hyp.get("experiments", [])]
                if chosen_hyp
                else []
            )

            # Look up the human-readable name
            rule = RULE_BY_ID.get(confirmed_cause_id)
            root_cause_text = rule.display_name if rule else confirmed_cause_id

            # Get design info for the run
            design_name = ""
            pdk = ""
            try:
                with get_db() as db2:
                    dr = db2.execute(
                        text(
                            """
                            SELECT d.name AS design_name, d.pdk
                            FROM runs r JOIN designs d ON d.id = r.design_id
                            WHERE r.id = :run_id
                            """
                        ),
                        {"run_id": run_id},
                    ).mappings().first()
                    if dr:
                        design_name = dr["design_name"] or ""
                        pdk = dr["pdk"] or ""
            except Exception:
                pass

            # Phase B: update rule weights based on this confirmation
            update_weights(
                confirmed_cause_id=confirmed_cause_id,
                top_hypotheses=hypotheses,
            )

            from eda_agent.agent.memory import save_case
            case_id = save_case(
                design_name=design_name,
                symptoms=symptoms,
                root_cause=root_cause_text,
                pdk=pdk,
                actions=actions,
                result_metrics={"inference_id": inference_id},
            )

    except Exception:
        logger.exception("confirm() failed for inference_id=%s", inference_id)
        return {"status": "error", "inference_id": inference_id}

    return {
        "status": "confirmed",
        "inference_id": inference_id,
        "confirmed_cause_id": confirmed_cause_id,
        "case_id": case_id,
    }
