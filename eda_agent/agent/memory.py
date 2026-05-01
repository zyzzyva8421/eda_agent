"""Session memory for the EDA agent.

Keeps a bounded history of (role, content) message pairs and a scratchpad
for the current ReAct iteration so the planner can build coherent prompts
across multiple tool calls.

Persistent case memory is stored in PostgreSQL (``case_memory`` table) and
surfaced through :func:`save_case` and :func:`search_similar_cases`.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_name: str | None = None   # set when role == "tool"
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None  # set when role == "assistant" and using tools


class AgentMemory:
    """Bounded message history + key-value scratchpad for a single session."""

    def __init__(self, max_messages: int = 40) -> None:
        self._history: deque[Message] = deque(maxlen=max_messages)
        self._scratchpad: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Message history
    # ------------------------------------------------------------------

    def add(self, msg: Message) -> None:
        self._history.append(msg)

    def add_user(self, content: str) -> None:
        self.add(Message(role="user", content=content))

    def add_assistant(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.add(Message(role="assistant", content=content, tool_calls=tool_calls))

    def add_tool_result(
        self, tool_name: str, content: str, tool_call_id: str | None = None
    ) -> None:
        self.add(
            Message(
                role="tool",
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
        )

    def get_messages(self, system_prompt: str = "") -> list[dict[str, Any]]:
        """Return message list in OpenAI-compatible chat format."""
        msgs: list[dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in self._history:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "tool":
                if m.tool_name:
                    entry["name"] = m.tool_name
                if m.tool_call_id:
                    entry["tool_call_id"] = m.tool_call_id
            elif m.role == "assistant" and m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            msgs.append(entry)
        return msgs

    def clear(self) -> None:
        self._history.clear()

    @classmethod
    def from_messages(
        cls,
        messages: list[dict],
        max_messages: int = 40,
    ) -> "AgentMemory":
        """Reconstruct an :class:`AgentMemory` from a serialised message list.

        The format is the OpenAI-compatible list returned by
        :meth:`get_messages` (without the system message).
        """
        mem = cls(max_messages=max_messages)
        for m in messages:
            role = m.get("role", "")
            content = m.get("content") or ""
            if role == "system":
                continue
            elif role == "user":
                mem.add_user(content)
            elif role == "assistant":
                mem.add_assistant(content, tool_calls=m.get("tool_calls"))
            elif role == "tool":
                mem.add_tool_result(
                    m.get("name", ""),
                    content,
                    tool_call_id=m.get("tool_call_id"),
                )
        return mem

    # ------------------------------------------------------------------
    # Scratchpad (per-session key-value store)
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        self._scratchpad[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._scratchpad.get(key, default)

    def extract_design_context(self) -> dict[str, str]:
        """Extract design context from conversation history.
        
        Looks for design_name, pdk, and config_path from previous tool calls.
        Returns a dict with available context.
        """
        context: dict[str, str] = {}
        
        # Look through tool results for design info
        for msg in self._history:
            if msg.role == "tool" and msg.tool_name in ("run_eda_stage", "run_eda_flow"):
                try:
                    import json
                    # Parse the tool result to extract design info
                    result = json.loads(msg.content)
                    if isinstance(result, dict):
                        # Try to extract from result
                        if "design_name" not in context:
                            context["design_name"] = result.get("design_name", "")
                        if "pdk" not in context:
                            context["pdk"] = result.get("pdk", "")
                except Exception:
                    pass
        
        # Also check scratchpad
        for key in ("design_name", "pdk", "config_path"):
            if key not in context:
                val = self.get(key)
                if val:
                    context[key] = val
        
        # Remove empty values
        return {k: v for k, v in context.items() if v}

    def __len__(self) -> int:
        return len(self._history)


# ── Persistent case memory (PostgreSQL) ──────────────────────────────────────

def save_case(
    design_name: str,
    symptoms: str,
    root_cause: str,
    pdk: str = "",
    actions: list[str] | None = None,
    result_metrics: dict[str, Any] | None = None,
) -> int:
    """Persist a resolved debugging case and return its DB id.

    Uses the shared SQLAlchemy session from :mod:`eda_agent.db.session` so no
    extra connection parameters are needed.
    """
    from sqlalchemy import text as _text

    from eda_agent.db.session import get_db

    actions_val = actions or []
    metrics_val = result_metrics or {}

    with get_db() as db:
        row = db.execute(
            _text(
                """
                INSERT INTO case_memory
                    (design_name, pdk, symptoms, root_cause, actions, result_metrics)
                VALUES
                    (:design_name, :pdk, :symptoms, :root_cause,
                     :actions::jsonb, :metrics::jsonb)
                RETURNING id
                """
            ),
            {
                "design_name": design_name,
                "pdk": pdk,
                "symptoms": symptoms,
                "root_cause": root_cause,
                "actions": __import__("json").dumps(actions_val),
                "metrics": __import__("json").dumps(metrics_val),
            },
        ).first()
        case_id: int = row[0]
    logger.info("Saved case #%d for design '%s'", case_id, design_name)
    return case_id


def search_similar_cases(
    query: str,
    design_name: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return the top-*limit* cases whose symptoms/root_cause match *query*.

    Uses PostgreSQL full-text search (``plainto_tsquery``).  Falls back to an
    ILIKE scan when no FTS matches are found so the caller always gets *some*
    results on small datasets.

    Parameters
    ----------
    query:
        Free-text description of the current issue.
    design_name:
        Optional filter – restrict results to this design.
    limit:
        Maximum number of cases to return.
    """
    import json as _json

    from sqlalchemy import text as _text

    from eda_agent.db.session import get_db

    design_filter = "AND design_name = :design_name" if design_name else ""

    fts_sql = _text(
        f"""
        SELECT id, design_name, pdk, symptoms, root_cause, actions,
               result_metrics, created_at
        FROM case_memory
        WHERE to_tsvector('english', symptoms || ' ' || root_cause)
              @@ plainto_tsquery('english', :query)
        {design_filter}
        ORDER BY ts_rank(
            to_tsvector('english', symptoms || ' ' || root_cause),
            plainto_tsquery('english', :query)
        ) DESC
        LIMIT :limit
        """
    )
    fallback_sql = _text(
        f"""
        SELECT id, design_name, pdk, symptoms, root_cause, actions,
               result_metrics, created_at
        FROM case_memory
        WHERE symptoms ILIKE :pattern OR root_cause ILIKE :pattern
        {design_filter}
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )

    params: dict[str, Any] = {"query": query, "limit": limit}
    if design_name:
        params["design_name"] = design_name

    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row[0],
            "design_name": row[1],
            "pdk": row[2],
            "symptoms": row[3],
            "root_cause": row[4],
            "actions": row[5] if isinstance(row[5], list) else _json.loads(row[5] or "[]"),
            "result_metrics": row[6] if isinstance(row[6], dict) else _json.loads(row[6] or "{}"),
            "created_at": str(row[7]),
        }

    try:
        with get_db() as db:
            rows = db.execute(fts_sql, params).fetchall()
            if not rows:
                # Build ILIKE pattern from the first meaningful word
                keyword = query.split()[0] if query.split() else query
                fb_params: dict[str, Any] = {"pattern": f"%{keyword}%", "limit": limit}
                if design_name:
                    fb_params["design_name"] = design_name
                rows = db.execute(fallback_sql, fb_params).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        logger.warning("case memory search failed – DB may not be available", exc_info=True)
        return []

