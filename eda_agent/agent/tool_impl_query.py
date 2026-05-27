"""Implementation helpers for query-oriented tool operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

from eda_agent.db.repository import EDAQueryRepository
from eda_agent.db.session import get_db
from eda_agent.parsers import get_parser

logger = logging.getLogger(__name__)


def query_timing_impl(
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


def query_congestion_impl(
    run_id: int,
    x1: float | None = None,
    y1: float | None = None,
    x2: float | None = None,
    y2: float | None = None,
) -> list[dict[str, Any]]:
    with get_db() as db:
        return EDAQueryRepository.get_congestion(
            db,
            run_id,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
        )


def query_congestion_summary_impl(run_id: int) -> dict[str, Any]:
    """Return congestion summary metrics for a run.

    Primary source: parsed Innovus congestion report artifact.
    Fallback: congestion_hotspots aggregates when no summary artifact exists.
    """
    with get_db() as db:
        artifact_row = db.execute(
            text(
                """
                SELECT file_path, artifact_type
                FROM artifacts
                WHERE run_id = :run_id
                  AND artifact_type IN ('innovus_congestion', 'congestion')
                  AND file_path NOT LIKE '%_map.rpt'
                ORDER BY id ASC
                LIMIT 1
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

        if artifact_row:
            file_path = Path(str(artifact_row["file_path"]))
            if file_path.is_file():
                try:
                    parser_name = str(artifact_row["artifact_type"])
                    parser = get_parser(parser_name)
                    records = parser.parse_file(file_path)
                    summary = next((r for r in records if r.get("kind") == "summary"), None)
                    if summary:
                        return {
                            "run_id": run_id,
                            "source": "report",
                            **summary,
                        }
                except Exception:
                    logger.debug(
                        "query_congestion_summary: failed to parse artifact for run_id=%s",
                        run_id,
                        exc_info=True,
                    )

        hotspot_agg = db.execute(
            text(
                """
                SELECT COALESCE(MAX(overflow), 0) AS max_overflow,
                       COALESCE(SUM(overflow), 0) AS sum_overflow,
                       COUNT(*) AS hotspot_count
                FROM congestion_hotspots
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

    if hotspot_agg:
        return {
            "run_id": run_id,
            "source": "hotspot_fallback",
            "kind": "summary",
            "total_overflow": int(hotspot_agg["sum_overflow"] or 0),
            "max_overflow": int(hotspot_agg["max_overflow"] or 0),
            "hotspot_count": int(hotspot_agg["hotspot_count"] or 0),
        }
    return {"run_id": run_id, "error": "No congestion data found"}


def compare_runs_impl(run_id_a: int, run_id_b: int) -> dict[str, Any]:
    with get_db() as db:
        return EDAQueryRepository.compare_runs(db, run_id_a, run_id_b)


def query_flow_sessions_impl(
    design_name: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with get_db() as db:
        return EDAQueryRepository.get_flow_sessions(
            db,
            design_name=design_name,
            status=status,
            limit=limit,
        )


def query_session_trace_impl(
    session_id: int,
    stage: str | None = None,
    from_seq: int | None = None,
    to_seq: int | None = None,
    human_approved: bool | None = None,
) -> dict[str, Any]:
    with get_db() as db:
        return EDAQueryRepository.get_session_trace(
            db,
            session_id,
            stage=stage,
            from_seq=from_seq,
            to_seq=to_seq,
            human_approved=human_approved,
        )


def query_utilization_impl(
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


def query_power_impl(
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


def get_run_log_impl(run_id: int, lines: int = 50) -> dict[str, Any]:
    with get_db() as db:
        return EDAQueryRepository.get_run_log(db, run_id, lines=lines)
