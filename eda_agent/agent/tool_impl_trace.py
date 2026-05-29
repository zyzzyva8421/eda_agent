"""Implementation helpers for trace/lineage persistence logic."""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import text

from eda_agent.db.session import get_db, is_postgresql


def record_decision_trace_impl(
    session_id: int,
    source_run_id: int,
    target_run_id: int,
    *,
    llm_reason: str = "",
    llm_reason_structured: dict[str, Any] | None = None,
    inference_id: int | None = None,
    case_id: int | None = None,
    rule_id: str | None = None,
    human_approved: bool = False,
    get_db_fn: Any = get_db,
) -> None:
    """Persist lineage from diagnosis/suggestion to the next rerun."""
    with get_db_fn() as db:
        _cast = "CAST(:llm_reason_structured AS jsonb)" if is_postgresql() else ":llm_reason_structured"
        db.execute(
            text(
                f"""
                INSERT INTO decision_trace
                    (session_id, source_run_id, target_run_id,
                     inference_id, case_id, rule_id,
                     llm_reason, llm_reason_structured, human_approved)
                VALUES
                    (:session_id, :source_run_id, :target_run_id,
                     :inference_id, :case_id, :rule_id,
                     :llm_reason, {_cast}, :human_approved)
                """
            ),
            {
                "session_id": session_id,
                "source_run_id": source_run_id,
                "target_run_id": target_run_id,
                "inference_id": inference_id,
                "case_id": case_id,
                "rule_id": rule_id,
                "llm_reason": llm_reason,
                "llm_reason_structured": json.dumps(
                    llm_reason_structured
                    if llm_reason_structured is not None
                    else ({"kind": "text", "text": llm_reason} if llm_reason else None)
                ),
                "human_approved": human_approved,
            },
        )


def decision_reason_from_suggestion_impl(
    suggestion: dict[str, Any],
    prefix: str = "",
) -> str:
    """Build a compact textual rationale for decision_trace from suggestion output."""
    parts: list[str] = []
    if prefix:
        parts.append(prefix)

    reasoning = suggestion.get("reasoning")
    if isinstance(reasoning, list):
        parts.extend(str(item) for item in reasoning[:3])
    elif isinstance(reasoning, str):
        parts.append(reasoning)

    suggested = suggestion.get("suggested_params")
    if isinstance(suggested, dict) and suggested:
        parts.append(f"suggested_params={suggested}")

    source = suggestion.get("source")
    if source:
        parts.append(f"source={source}")

    return " | ".join(p for p in parts if p)


def decision_reason_structured_from_suggestion_impl(
    suggestion: dict[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """Build a structured rationale payload for decision_trace."""
    payload: dict[str, Any] = {"kind": "suggestion"}
    if prefix:
        payload["prefix"] = prefix

    reasoning = suggestion.get("reasoning")
    if isinstance(reasoning, list):
        payload["reasoning"] = [str(item) for item in reasoning[:3]]
    elif isinstance(reasoning, str) and reasoning.strip():
        payload["reasoning"] = [reasoning]

    suggested = suggestion.get("suggested_params")
    if isinstance(suggested, dict) and suggested:
        payload["suggested_params"] = suggested

    source = suggestion.get("source")
    if source:
        payload["source"] = str(source)

    return payload


def set_flow_session_inference_context_impl(
    session_id: int,
    *,
    inference_id: int | None = None,
    case_id: int | None = None,
    rule_id: str | None = None,
    get_db_fn: Any = get_db,
) -> None:
    """Persist latest inference/case/rule context on a flow session."""
    if inference_id is None and case_id is None and rule_id is None:
        return
    with get_db_fn() as db:
        db.execute(
            text(
                """
                UPDATE flow_sessions
                SET last_inference_id = COALESCE(:inference_id, last_inference_id),
                    last_case_id = COALESCE(:case_id, last_case_id),
                    last_rule_id = COALESCE(:rule_id, last_rule_id),
                    updated_at = now()
                WHERE id = :sid
                """
            ),
            {
                "sid": session_id,
                "inference_id": inference_id,
                "case_id": case_id,
                "rule_id": rule_id,
            },
        )


def set_flow_session_context_from_run_impl(
    run_id: int,
    *,
    inference_id: int | None = None,
    case_id: int | None = None,
    rule_id: str | None = None,
    get_db_fn: Any = get_db,
    set_flow_session_inference_context_fn: Callable[..., None] | None = None,
) -> None:
    """Resolve session_id by run_id and update session inference context."""
    with get_db_fn() as db:
        row = db.execute(
            text("SELECT session_id FROM runs WHERE id = :run_id"),
            {"run_id": run_id},
        ).first()
        if not row or row[0] is None:
            return
        sid = int(row[0])
    setter = set_flow_session_inference_context_fn or set_flow_session_inference_context_impl
    setter(
        sid,
        inference_id=inference_id,
        case_id=case_id,
        rule_id=rule_id,
        get_db_fn=get_db_fn,
    )


def latest_inference_context_for_run_impl(
    run_id: int,
    *,
    get_db_fn: Any = get_db,
) -> dict[str, Any]:
    """Best-effort lookup for inference/case context linked to *run_id*."""
    with get_db_fn() as db:
        session_ctx = db.execute(
            text(
                """
                SELECT fs.last_inference_id, fs.last_case_id, fs.last_rule_id
                FROM runs r
                JOIN flow_sessions fs ON fs.id = r.session_id
                WHERE r.id = :run_id
                """
            ),
            {"run_id": run_id},
        ).first()
        if session_ctx and any(v is not None for v in session_ctx):
            return {
                "inference_id": int(session_ctx[0]) if session_ctx[0] is not None else None,
                "case_id": int(session_ctx[1]) if session_ctx[1] is not None else None,
                "rule_id": session_ctx[2],
            }

        inf = db.execute(
            text(
                """
                SELECT id, chosen_cause, hypotheses
                FROM root_cause_inferences
                WHERE run_id = :run_id
                ORDER BY confirmed_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

        if not inf:
            return {"inference_id": None, "case_id": None, "rule_id": None}

        inference_id = int(inf["id"])
        rule_id: str | None = inf.get("chosen_cause")
        if not rule_id:
            hypotheses = inf.get("hypotheses") or []
            if isinstance(hypotheses, list) and hypotheses:
                first = hypotheses[0]
                if isinstance(first, dict):
                    rule_id = first.get("cause_id")

        case_row = db.execute(
            text(
                """
                SELECT id
                FROM case_memory
                WHERE result_metrics->>'inference_id' = :inference_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"inference_id": str(inference_id)},
        ).first()

        case_id = int(case_row[0]) if case_row else None
        return {
            "inference_id": inference_id,
            "case_id": case_id,
            "rule_id": rule_id,
        }
