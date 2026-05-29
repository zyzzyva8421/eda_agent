"""Session memory for the EDA agent.

Two layers of memory live in this module:

* :class:`AgentMemory` — short-term, per-session message history plus a
  structured scratchpad of durable session facts (design_name, pdk, …).
  The scratchpad has two namespaces: ``context`` (persisted across
  process restarts via :mod:`eda_agent.agent.session_store`) and
  ``_internal`` (volatile cache; recomputed each new process).

* :func:`save_case` / :func:`search_similar_cases` — persistent case
  memory stored in PostgreSQL ``case_memory``, surfaced to the planner
  so previous debugging sessions inform new ones.

The class is intentionally framework-agnostic: persistence wiring lives
in :mod:`eda_agent.agent.session_store`.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


# Per-tool-result character cap.  Long EDA log dumps would otherwise
# dominate the context window and may even bust LLM input limits.
DEFAULT_TOOL_RESULT_MAX_CHARS = 8 * 1024

# Rough characters-per-token estimate for the budget-aware view.  Good
# enough for trimming heuristics without pulling in tiktoken at runtime.
_CHARS_PER_TOKEN = 4
_OVERHEAD_TOKENS_PER_MESSAGE = 4  # role + bookkeeping tokens charged per msg

# Well-known scratchpad keys for L2 session facts.  Whenever a tool call
# exposes one of these (as an argument or in its return payload) we
# update the ``context`` namespace.
CONTEXT_KEYS: tuple[str, ...] = (
    "design_name",
    "pdk",
    "config_path",
    "design_config",
    "backend",
    "last_run_id",
    "run_id",
    "stage",
)


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_name: str | None = None        # set when role == "tool"
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None  # set on assistant tool turns


class AgentMemory:
    """Bounded message history + key-value scratchpad for a single session.

    Not thread-safe; each REPL or HTTP request creates its own instance.
    """

    def __init__(
        self,
        max_messages: int = 40,
        tool_result_max_chars: int = DEFAULT_TOOL_RESULT_MAX_CHARS,
    ) -> None:
        self._max_messages = max_messages
        self._tool_result_max_chars = tool_result_max_chars
        # We use a plain list and manage eviction manually so we can drop
        # (assistant tool_calls -> tool result) pairs atomically rather
        # than risk leaving an orphan tool message at the front.
        self._history: list[Message] = []
        self._scratchpad: dict[str, Any] = {"context": {}, "_internal": {}}

    # ------------------------------------------------------------------
    # Message history
    # ------------------------------------------------------------------

    def add(self, msg: Message) -> None:
        self._history.append(msg)
        self._evict_if_needed()

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
        # Truncate oversized payloads so a single noisy tool can't poison
        # the whole context window.
        if (
            self._tool_result_max_chars > 0
            and isinstance(content, str)
            and len(content) > self._tool_result_max_chars
        ):
            keep = self._tool_result_max_chars
            dropped = len(content) - keep
            content = (
                content[:keep]
                + f"\n…<truncated {dropped} chars; "
                f"use job_logs / query_timing for the full payload>"
            )
        self.add(
            Message(
                role="tool",
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
        )

    def _evict_if_needed(self) -> None:
        """Trim oldest messages while keeping tool_calls/result pairs together."""
        max_n = self._max_messages
        if max_n <= 0 or len(self._history) <= max_n:
            return
        # We drop one *group* at a time, where a group starts at the first
        # non-tool message and includes any tool messages that immediately
        # follow (each tool message belongs to the preceding assistant
        # tool_calls turn).  This guarantees we never leave an orphan
        # tool message at the front, which would otherwise make the next
        # LLM request 400.
        while len(self._history) > max_n:
            # Drop the very first message…
            self._history.pop(0)
            # …and any tool messages immediately after it that belonged
            # to the assistant turn we just removed.
            while self._history and self._history[0].role == "tool":
                self._history.pop(0)

    def get_messages(
        self,
        system_prompt: str = "",
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return message list in OpenAI-compatible chat format.

        When *max_tokens* is given, the oldest message groups are dropped
        (preserving system prompt + tool_call/result pairing) until the
        estimated token budget fits.  The estimate is intentionally
        coarse (characters / 4) so this stays fast and dependency-free.
        """
        msgs: list[dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in self._history:
            msgs.append(self._serialise(m))

        if max_tokens is not None and max_tokens > 0:
            msgs = _trim_to_token_budget(msgs, max_tokens)
        return msgs

    @staticmethod
    def _serialise(m: Message) -> dict[str, Any]:
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.role == "tool":
            if m.tool_name:
                entry["name"] = m.tool_name
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
        elif m.role == "assistant" and m.tool_calls:
            entry["tool_calls"] = m.tool_calls
        return entry

    def clear(self) -> None:
        """Drop message history, but keep the scratchpad."""
        self._history.clear()

    def forget(self) -> None:
        """Drop everything — history *and* scratchpad."""
        self._history.clear()
        self._scratchpad = {"context": {}, "_internal": {}}

    # ------------------------------------------------------------------
    # Byte-budget enforcement (for persistence layer)
    # ------------------------------------------------------------------

    def shrink_to_byte_budget(self, max_bytes: int) -> None:
        """Drop oldest message groups until the JSON payload fits."""
        if max_bytes <= 0:
            return
        while self._history:
            payload = json.dumps([self._serialise(m) for m in self._history])
            if len(payload.encode("utf-8")) <= max_bytes:
                return
            # Drop one group from the front.
            self._history.pop(0)
            while self._history and self._history[0].role == "tool":
                self._history.pop(0)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, *, persist_internal: bool = False) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this memory.

        ``_internal`` keys (cache, retrieval results, transient flags)
        are stripped by default — they are recomputed in each new
        process.  Callers can pass ``persist_internal=True`` for tests
        or debugging dumps.
        """
        scratch: dict[str, Any] = {"context": dict(self._scratchpad.get("context", {}))}
        if persist_internal:
            scratch["_internal"] = dict(self._scratchpad.get("_internal", {}))
        return {
            "messages": [self._serialise(m) for m in self._history],
            "scratchpad": scratch,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        max_messages: int = 40,
    ) -> "AgentMemory":
        """Inverse of :meth:`to_dict`.

        The serialised messages list is sanitised so that orphan tool
        messages (i.e. ``role == "tool"`` without a preceding
        ``assistant`` turn carrying a matching ``tool_call_id``) are
        dropped.  Otherwise the next LLM call would 400.
        """
        mem = cls(max_messages=max_messages)
        messages = payload.get("messages") or []
        mem._load_messages(messages)
        scratch = payload.get("scratchpad") or {}
        if isinstance(scratch, dict):
            mem._scratchpad["context"] = dict(scratch.get("context") or {})
            internal = scratch.get("_internal")
            if isinstance(internal, dict):
                mem._scratchpad["_internal"] = dict(internal)
        return mem

    @classmethod
    def from_messages(
        cls,
        messages: list[dict],
        max_messages: int = 40,
    ) -> "AgentMemory":
        """Backwards-compatible constructor used by old session rows."""
        return cls.from_dict({"messages": messages, "scratchpad": {}}, max_messages)

    def _load_messages(self, messages: list[dict]) -> None:
        """Internal helper used by :meth:`from_dict`.

        Performs pair-awareness sanitisation: a ``tool`` message is kept
        only if the most recent assistant turn declared its
        ``tool_call_id`` in ``tool_calls``.
        """
        pending_ids: set[str] = set()
        for m in messages:
            role = m.get("role", "")
            content = m.get("content") or ""
            if role == "system":
                continue
            if role == "user":
                pending_ids.clear()
                self._history.append(Message(role="user", content=content))
            elif role == "assistant":
                tc = m.get("tool_calls") or None
                pending_ids = {
                    str(t.get("id")) for t in (tc or []) if t and t.get("id")
                }
                self._history.append(
                    Message(role="assistant", content=content, tool_calls=tc)
                )
            elif role == "tool":
                tool_call_id = m.get("tool_call_id")
                if tool_call_id and str(tool_call_id) in pending_ids:
                    self._history.append(
                        Message(
                            role="tool",
                            content=content,
                            tool_name=m.get("name") or "",
                            tool_call_id=tool_call_id,
                        )
                    )
                    pending_ids.discard(str(tool_call_id))
                else:
                    logger.debug(
                        "Dropping orphan tool message (call_id=%s, name=%s)",
                        tool_call_id,
                        m.get("name"),
                    )
        self._evict_if_needed()

    # ------------------------------------------------------------------
    # Scratchpad (per-session key-value store)
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key*.

        Keys starting with ``_`` are treated as volatile (``_internal``
        namespace) and will NOT be persisted across process restarts.
        All other keys live in the ``context`` namespace, which IS
        persisted.
        """
        bucket = "_internal" if key.startswith("_") else "context"
        self._scratchpad.setdefault(bucket, {})[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        bucket = "_internal" if key.startswith("_") else "context"
        return self._scratchpad.get(bucket, {}).get(key, default)

    def context(self) -> dict[str, Any]:
        """Return a copy of the durable context namespace."""
        return dict(self._scratchpad.get("context", {}))

    def update_context_from_tool(
        self,
        arguments: dict[str, Any] | None,
        tool_result: str | dict | None,
    ) -> None:
        """Incrementally update context facts from a tool call.

        Looks at both *arguments* (what the LLM asked for) and
        *tool_result* (what the backend reported) for any key in
        :data:`CONTEXT_KEYS`.  Newer values overwrite older ones so the
        scratchpad always reflects the most recent run.
        """
        parsed_result: Any = tool_result
        if isinstance(tool_result, str):
            try:
                parsed_result = json.loads(tool_result)
            except Exception:
                parsed_result = None

        for source in (arguments, parsed_result):
            if not isinstance(source, dict):
                continue
            for key in CONTEXT_KEYS:
                val = source.get(key)
                if val in (None, ""):
                    continue
                # design_config from arguments maps onto config_path for
                # consistency with what the planner exposes.
                if key == "design_config":
                    self.set("config_path", val)
                else:
                    self.set(key, val)

    def extract_design_context(self) -> dict[str, str]:
        """Return the durable context as a flat ``str → str`` dict.

        Reads from the ``context`` namespace of the scratchpad which is
        populated by :meth:`update_context_from_tool` and persisted
        across process restarts via the session store.  Non-string
        values are coerced via ``str()`` for backwards compatibility
        with the previous planner code which expected a string-only
        dict.
        """
        return {k: str(v) for k, v in self.context().items() if v not in (None, "")}

    def __len__(self) -> int:
        return len(self._history)


# ---------------------------------------------------------------------------
# Token budget helper
# ---------------------------------------------------------------------------


def _trim_to_token_budget(
    messages: list[dict[str, Any]], max_tokens: int
) -> list[dict[str, Any]]:
    """Drop oldest message groups until estimated tokens ≤ *max_tokens*.

    System prompt (index 0, role=system) is always preserved.  Tool
    messages are dropped together with their preceding assistant turn to
    keep ``tool_call_id`` pairing intact.
    """

    def estimate(msgs: list[dict[str, Any]]) -> int:
        total = 0
        for m in msgs:
            content = m.get("content") or ""
            total += len(content) // _CHARS_PER_TOKEN + _OVERHEAD_TOKENS_PER_MESSAGE
            for tc in m.get("tool_calls") or []:
                total += len(json.dumps(tc)) // _CHARS_PER_TOKEN
        return total

    if estimate(messages) <= max_tokens:
        return messages

    has_system = bool(messages) and messages[0].get("role") == "system"
    head = [messages[0]] if has_system else []
    rest = messages[1:] if has_system else list(messages)

    while rest and estimate(head + rest) > max_tokens:
        # Drop the first message and any tool messages glued to it.
        rest.pop(0)
        while rest and rest[0].get("role") == "tool":
            rest.pop(0)
    return head + rest


# ── Persistent case memory (PostgreSQL) ──────────────────────────────────────


def save_case(
    design_name: str,
    symptoms: str,
    root_cause: str,
    pdk: str = "",
    actions: list[str] | None = None,
    result_metrics: dict[str, Any] | None = None,
) -> int:
    """Persist a resolved debugging case and return its DB id."""
    from sqlalchemy import text as _text

    from eda_agent.db.session import get_db, supports_postgresql_jsonb

    actions_val = actions or []
    metrics_val = result_metrics or {}

    _jc = "::jsonb" if supports_postgresql_jsonb() else ""
    with get_db() as db:
        row = db.execute(
            _text(
                f"""
                INSERT INTO case_memory
                    (design_name, pdk, symptoms, root_cause, actions, result_metrics)
                VALUES
                    (:design_name, :pdk, :symptoms, :root_cause,
                     :actions{_jc}, :metrics{_jc})
                RETURNING id
                """
            ),
            {
                "design_name": design_name,
                "pdk": pdk,
                "symptoms": symptoms,
                "root_cause": root_cause,
                "actions": json.dumps(actions_val),
                "metrics": json.dumps(metrics_val),
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

    Uses PostgreSQL full-text search (``plainto_tsquery``).  Falls back
    to an ILIKE scan when no FTS matches are found so the caller always
    gets *some* results on small datasets.
    """
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
            "actions": row[5]
            if isinstance(row[5], list)
            else json.loads(row[5] or "[]"),
            "result_metrics": row[6]
            if isinstance(row[6], dict)
            else json.loads(row[6] or "{}"),
            "created_at": str(row[7]),
        }

    try:
        with get_db() as db:
            rows = db.execute(fts_sql, params).fetchall()
            if not rows:
                # Build ILIKE pattern from the first meaningful word
                keyword = query.split()[0] if query.split() else query
                fb_params: dict[str, Any] = {
                    "pattern": f"%{keyword}%",
                    "limit": limit,
                }
                if design_name:
                    fb_params["design_name"] = design_name
                rows = db.execute(fallback_sql, fb_params).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        logger.warning(
            "case memory search failed – DB may not be available",
            exc_info=True,
        )
        return []
