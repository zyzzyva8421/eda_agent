"""Implementation helpers for trace/lineage persistence logic."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from eda_agent.db.session import get_db


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
        db.execute(
            text(
                """
                INSERT INTO decision_trace
                    (session_id, source_run_id, target_run_id,
                     inference_id, case_id, rule_id,
                     llm_reason, llm_reason_structured, human_approved)
                VALUES
                    (:session_id, :source_run_id, :target_run_id,
                     :inference_id, :case_id, :rule_id,
                     :llm_reason, CAST(:llm_reason_structured AS jsonb), :human_approved)
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
