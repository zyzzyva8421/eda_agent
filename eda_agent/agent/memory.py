"""Session memory for the EDA agent.

Keeps a bounded history of (role, content) message pairs and a scratchpad
for the current ReAct iteration so the planner can build coherent prompts
across multiple tool calls.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal


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

    def __len__(self) -> int:
        return len(self._history)
