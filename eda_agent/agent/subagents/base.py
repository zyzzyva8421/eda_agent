"""Base types for multi-agent orchestration."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal

AgentStatus = Literal["ok", "error", "needs_approval"]


@dataclass
class AgentEnvelope:
    """Standard message envelope exchanged between sub-agents."""

    task_id: str
    agent: str
    session_id: int | None = None
    run_id: int | None = None
    objective: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = "ok"
    error: str = ""

    @classmethod
    def ok(
        cls,
        *,
        task_id: str,
        agent: str,
        objective: str,
        session_id: int | None = None,
        run_id: int | None = None,
        constraints: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> "AgentEnvelope":
        return cls(
            task_id=task_id,
            agent=agent,
            session_id=session_id,
            run_id=run_id,
            objective=objective,
            constraints=constraints or {},
            inputs=inputs or {},
            outputs=outputs or {},
            status="ok",
        )

    @classmethod
    def error_result(
        cls,
        *,
        task_id: str,
        agent: str,
        objective: str,
        error: str,
        session_id: int | None = None,
        run_id: int | None = None,
        constraints: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> "AgentEnvelope":
        return cls(
            task_id=task_id,
            agent=agent,
            session_id=session_id,
            run_id=run_id,
            objective=objective,
            constraints=constraints or {},
            inputs=inputs or {},
            status="error",
            error=error,
        )


class BaseSubAgent(abc.ABC):
    """Abstract base class for specialized sub-agents."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique short name of this sub-agent."""

    @abc.abstractmethod
    def run(self, task: AgentEnvelope) -> AgentEnvelope:
        """Run this sub-agent and return an updated envelope."""
