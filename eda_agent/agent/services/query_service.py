"""Read-only query service for sub-agent analysis workflows."""

from __future__ import annotations

from typing import Any

from eda_agent.db.repository import EDAQueryRepository
from eda_agent.db.session import get_db


class AgentQueryService:
    """Encapsulate analysis queries used by sub-agents.

    This keeps sub-agents independent from tool-dispatch implementation
    details and avoids cross-layer imports from ``agent.tools``.
    """

    def query_timing(
        self,
        *,
        design_name: str,
        stage: str | None = None,
        run_id: int | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        with get_db() as db:
            return EDAQueryRepository.get_timing(
                db,
                design_name,
                stage=stage,
                run_id=run_id,
                limit=limit,
            )

    def query_utilization(
        self,
        *,
        design_name: str,
        stage: str | None = None,
        run_id: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_db() as db:
            return EDAQueryRepository.get_utilization(
                db,
                design_name,
                stage=stage,
                run_id=run_id,
                limit=limit,
            )

    def query_power(
        self,
        *,
        design_name: str,
        stage: str | None = None,
        run_id: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_db() as db:
            return EDAQueryRepository.get_power(
                db,
                design_name,
                stage=stage,
                run_id=run_id,
                limit=limit,
            )
