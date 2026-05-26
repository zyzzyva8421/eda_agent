"""Typed contracts for multi-agent orchestration payloads."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class StatusSummary(TypedDict):
    total: int
    ok: int
    needs_approval: int
    error: int
    has_error: bool


class DecisionView(TypedDict):
    candidate_experiments: list[dict[str, Any]]
    constraint_warnings: list[str]
    signoff_ready: bool
    next_action: str
    risk_level: str
    requires_approval: bool


class HitlGate(TypedDict):
    blocked: bool
    status: Literal["auto_execute", "needs_approval"]
    reason: str


class MultiAgentCycleResult(TypedDict):
    contract_version: str
    task_id: str
    session_id: int | None
    run_id: int | None
    objective: str
    agents: list[str]
    envelopes: list[dict[str, Any]]
    merged: dict[str, Any]
    status_summary: StatusSummary
    decision_view: DecisionView
    gate: HitlGate
