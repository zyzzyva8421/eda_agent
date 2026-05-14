"""Guardrails – program-level safety interceptor for agent tool calls.

Every tool call passes through :func:`check` before execution.  The function
returns a :class:`GuardrailResult` that ``execute_tool`` uses to decide
whether to proceed, warn, or block.

Risk levels
-----------
SAFE   – execute immediately, no side-effects on result.
WARN   – execute but append a ``_warning`` field to the returned dict.
BLOCK  – refuse execution; return a structured ``blocked`` response.
         The LLM must surface the reason to the user and wait for explicit
         confirmation.  On re-call the LLM must include
         ``_guardrail_confirmed=true`` in the arguments to bypass the block.

Confirmation protocol
---------------------
1. ``execute_tool("run_eda_flow", {..., "clean": True})``
   → blocked, reason explained.
2. User says "确认，继续" (or any affirmative).
3. LLM re-calls: ``execute_tool("run_eda_flow", {..., "clean": True,
                                 "_guardrail_confirmed": True})``
4. ``check()`` sees the flag, skips the block check, returns SAFE/WARN.

The ``_guardrail_confirmed`` key is stripped from ``arguments`` by
``execute_tool`` before forwarding to the actual implementation so tool
functions never receive it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    SAFE = "safe"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class GuardrailResult:
    level: RiskLevel
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return self.level == RiskLevel.BLOCK

    def blocked_response(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """JSON-serialisable response returned to the LLM when blocked."""
        return {
            "blocked": True,
            "tool": tool_name,
            "reason": self.reason,
            "to_proceed": (
                "请告知用户此操作的风险并等待明确确认。"
                "用户确认后，在参数中加入 _guardrail_confirmed=true 重新调用本工具。"
            ),
        }


# ── Individual check helpers ──────────────────────────────────────────────────

def _check_clean_flag(args: dict[str, Any]) -> GuardrailResult | None:
    """Block destructive clean operations."""
    clean = args.get("clean") or args.get("params", {}) and args.get("params", {}).get("_clean")
    if clean:
        return GuardrailResult(
            level=RiskLevel.BLOCK,
            reason=(
                "clean=True 将删除所有已有的构建产物并强制重跑整个 flow，"
                "这是不可逆操作。请确认是否继续。"
            ),
        )
    return None


def _check_utilization(args: dict[str, Any]) -> GuardrailResult | None:
    """Warn or block extreme CORE_UTILIZATION values."""
    params: dict[str, Any] = args.get("params") or {}
    raw = params.get("CORE_UTILIZATION")
    if raw is None:
        return None
    try:
        val = float(str(raw).rstrip("%"))
    except ValueError:
        return None

    if val > 95:
        return GuardrailResult(
            level=RiskLevel.BLOCK,
            reason=(
                f"CORE_UTILIZATION={val}% 超出安全上限（95%）。"
                "过高的 utilization 几乎必然导致 routing 失败和大量 DRC。"
                "请降低至 85% 以下再重试。"
            ),
        )
    warnings: list[str] = []
    if val > 85:
        warnings.append(
            f"CORE_UTILIZATION={val}% 较高（>85%），可能引发拥塞和 routing 困难。"
        )
    if val < 25:
        warnings.append(
            f"CORE_UTILIZATION={val}% 异常低（<25%），面积浪费严重，请确认是否为预期值。"
        )
    if warnings:
        return GuardrailResult(level=RiskLevel.WARN, warnings=warnings)
    return None


def _check_long_running(tool_name: str) -> GuardrailResult | None:
    """Warn before multi-hour autonomous tuning loops."""
    long_running = {"tune_ppa", "tune_ppa_multistage", "tune_congestion_with_blockage"}
    if tool_name in long_running:
        return GuardrailResult(
            level=RiskLevel.WARN,
            warnings=[
                f"{tool_name} 将自动运行多轮 EDA flow，可能耗时数小时并占用大量计算资源。"
            ],
        )
    return None


def _check_cancel(tool_name: str) -> GuardrailResult | None:
    """Warn before cancelling a job."""
    if tool_name == "cancel_job":
        return GuardrailResult(
            level=RiskLevel.WARN,
            warnings=["cancel_job 将中止正在运行的任务，操作不可逆。"],
        )
    return None


# ── Checker registry (ordered; first BLOCK wins) ─────────────────────────────

_CHECKERS = [
    lambda name, args: _check_clean_flag(args),
    lambda name, args: _check_utilization(args),
    lambda name, args: _check_long_running(name),
    lambda name, args: _check_cancel(name),
]


# ── Public API ────────────────────────────────────────────────────────────────

def check(tool_name: str, arguments: dict[str, Any]) -> GuardrailResult:
    """Run all guardrail checks for *tool_name* + *arguments*.

    Returns a :class:`GuardrailResult`.  The caller should inspect
    ``result.is_blocked`` and act accordingly.

    Checks are skipped entirely when ``arguments`` contains
    ``_guardrail_confirmed=True`` (set by the LLM after user approval).
    """
    if arguments.get("_guardrail_confirmed"):
        logger.info("Guardrail bypassed by explicit confirmation for tool '%s'", tool_name)
        return GuardrailResult(level=RiskLevel.SAFE)

    warnings: list[str] = []

    for checker in _CHECKERS:
        result = checker(tool_name, arguments)
        if result is None:
            continue
        if result.level == RiskLevel.BLOCK:
            logger.warning(
                "Guardrail BLOCK: tool=%s reason=%s", tool_name, result.reason
            )
            return result
        if result.level == RiskLevel.WARN:
            warnings.extend(result.warnings)

    if warnings:
        return GuardrailResult(level=RiskLevel.WARN, warnings=warnings)

    return GuardrailResult(level=RiskLevel.SAFE)
