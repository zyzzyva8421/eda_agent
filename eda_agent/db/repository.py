"""Unified EDA query repository – single home for all analytics SQL.

Every read method accepts an active SQLAlchemy session as its first
argument so callers can share transactions when needed.

Usage::

    from eda_agent.db.repository import EDAQueryRepository

    with get_db() as db:
        repo = EDAQueryRepository(db)
        rows = repo.get_timing("gcd", stage="route", limit=10)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


class EDAQueryRepository:
    """Stateless repository – all methods receive *db* explicitly."""

    __slots__ = ()

    # ── Timing ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_timing(
        db: Any,
        design_name: str,
        *,
        stage: str | None = None,
        run_id: int | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return ``{"summary": [...], "paths": [...]}`` for a design."""
        conditions = ["d.name = :design_name"]
        params: dict[str, Any] = {"design_name": design_name, "limit": limit}
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if run_id:
            conditions.append("r.id = :run_id")
            params["run_id"] = run_id
        where = " AND ".join(conditions)

        summary_rows = db.execute(
            text(
                f"""
                SELECT ts.id, r.id AS run_id, r.stage, b.name AS backend,
                       ts.view, ts.wns_ns, ts.tns_ns, ts.failing_endpoints,
                       ts.fmax_mhz, ts.clock_skew_ns,
                       ts.max_slew_violations, ts.max_fanout_violations,
                       ts.max_cap_violations, ts.setup_violations, ts.hold_violations,
                       ts.critical_path_delay_ns, ts.slack_cpd_ratio_pct,
                       r.params, r.created_at
                FROM timing_summary ts
                JOIN runs r    ON r.id  = ts.run_id
                JOIN designs d ON d.id  = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()

        path_rows = db.execute(
            text(
                f"""
                SELECT tp.id, tp.run_id, tp.startpoint, tp.endpoint,
                       tp.path_group, tp.slack_ns
                FROM timing_paths tp
                JOIN runs r ON r.id = tp.run_id
                JOIN designs d ON d.id = r.design_id
                WHERE {where}
                ORDER BY tp.slack_ns ASC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()

        return {
            "summary": [dict(r) for r in summary_rows],
            "paths": [dict(r) for r in path_rows],
        }

    # ── Congestion ─────────────────────────────────────────────────────────

    @staticmethod
    def get_congestion(
        db: Any,
        run_id: int,
        *,
        x1: float | None = None,
        y1: float | None = None,
        x2: float | None = None,
        y2: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if all(v is not None for v in [x1, y1, x2, y2]):
            bbox_wkt = f"POLYGON(({x1} {y1},{x2} {y1},{x2} {y2},{x1} {y2},{x1} {y1}))"  # noqa: S608
            rows = db.execute(
                text(
                    """
                    SELECT id, run_id, overflow, layer,
                           ST_AsText(geom) AS geom_wkt
                    FROM congestion_hotspots
                    WHERE run_id = :run_id
                      AND ST_Intersects(geom, ST_GeomFromText(:bbox, 0))
                    ORDER BY overflow DESC
                    """
                ),
                {"run_id": run_id, "bbox": bbox_wkt},
            ).mappings().fetchall()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT id, run_id, overflow, layer,
                           ST_AsText(geom) AS geom_wkt
                    FROM congestion_hotspots
                    WHERE run_id = :run_id
                    ORDER BY overflow DESC
                    LIMIT :limit
                    """
                ),
                {"run_id": run_id, "limit": limit},
            ).mappings().fetchall()
        return [dict(r) for r in rows]

    # ── Utilization ────────────────────────────────────────────────────────

    @staticmethod
    def get_utilization(
        db: Any,
        design_name: str,
        *,
        stage: str | None = None,
        run_id: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        conditions = ["d.name = :design_name"]
        params: dict[str, Any] = {"design_name": design_name, "limit": limit}
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if run_id:
            conditions.append("r.id = :run_id")
            params["run_id"] = run_id
        where = " AND ".join(conditions)
        rows = db.execute(
            text(
                f"""
                SELECT us.id, r.id AS run_id, r.stage, b.name AS backend,
                       us.design_area_um2, us.utilization_pct,
                       us.num_cells, us.num_registers, r.created_at
                FROM utilization_summary us
                JOIN runs r    ON r.id  = us.run_id
                JOIN designs d ON d.id  = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()
        return [dict(r) for r in rows]

    # ── Power ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_power(
        db: Any,
        design_name: str,
        *,
        stage: str | None = None,
        run_id: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        conditions = ["d.name = :design_name"]
        params: dict[str, Any] = {"design_name": design_name, "limit": limit}
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if run_id:
            conditions.append("r.id = :run_id")
            params["run_id"] = run_id
        where = " AND ".join(conditions)
        rows = db.execute(
            text(
                f"""
                SELECT ps.id, r.id AS run_id, r.stage, b.name AS backend,
                       ps.internal_power_w, ps.switching_power_w,
                       ps.leakage_power_w, ps.total_power_w, r.created_at
                FROM power_summary ps
                JOIN runs r    ON r.id  = ps.run_id
                JOIN designs d ON d.id  = r.design_id
                JOIN backends b ON b.id = r.backend_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()
        return [dict(r) for r in rows]

    # ── Run comparison ─────────────────────────────────────────────────────

    @staticmethod
    def compare_runs(
        db: Any,
        run_id_a: int,
        run_id_b: int,
    ) -> dict[str, Any]:
        def _fetch(rid: int) -> dict:
            row = db.execute(
                text(
                    """
                    SELECT r.id, r.stage, r.params, r.status,
                           b.name AS backend, d.name AS design,
                           ts.wns_ns, ts.tns_ns, ts.failing_endpoints
                    FROM runs r
                    JOIN backends b ON b.id = r.backend_id
                    JOIN designs d ON d.id = r.design_id
                    LEFT JOIN timing_summary ts ON ts.run_id = r.id
                    WHERE r.id = :rid
                    ORDER BY ts.wns_ns ASC
                    LIMIT 1
                    """
                ),
                {"rid": rid},
            ).mappings().first()
            return dict(row) if row else {}

        a = _fetch(run_id_a)
        b = _fetch(run_id_b)

        diff: dict[str, Any] = {"run_a": a, "run_b": b, "delta": {}}
        for metric in ("wns_ns", "tns_ns", "failing_endpoints"):
            va, vb = a.get(metric), b.get(metric)
            if va is not None and vb is not None:
                diff["delta"][metric] = round(vb - va, 6)
        return diff

    # ── Run log ────────────────────────────────────────────────────────────

    @staticmethod
    def get_run_log(
        db: Any,
        run_id: int,
        *,
        lines: int = 50,
    ) -> dict[str, Any]:
        row = db.execute(
            text(
                "SELECT r.log_path, r.stage, r.status, d.name AS design_name "
                "FROM runs r JOIN designs d ON d.id = r.design_id WHERE r.id = :rid"
            ),
            {"rid": run_id},
        ).mappings().first()

        if not row:
            return {"error": f"Run {run_id} not found"}

        log_path = row["log_path"]
        if not log_path:
            return {"error": f"No log_path for run {run_id}"}

        log_file = Path(log_path)
        if not log_file.is_file():
            return {"error": f"Log file not found: {log_path}"}

        try:
            all_lines = log_file.read_text().splitlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {
                "run_id": run_id,
                "stage": row["stage"],
                "status": row["status"],
                "design_name": row["design_name"],
                "log_path": str(log_path),
                "log_content": "\n".join(last_lines),
            }
        except Exception as e:
            return {"error": f"Failed to read log: {e}"}

    # ── Run listing ────────────────────────────────────────────────────────

    @staticmethod
    def list_runs(
        db: Any,
        *,
        design_name: str | None = None,
        stage: str | None = None,
        backend: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conditions = ["1=1"]
        params: dict[str, Any] = {"limit": limit}
        if design_name:
            conditions.append("d.name = :design_name")
            params["design_name"] = design_name
        if stage:
            conditions.append("r.stage = :stage")
            params["stage"] = stage
        if backend:
            conditions.append("b.name = :backend")
            params["backend"] = backend
        where = " AND ".join(conditions)
        rows = db.execute(
            text(
                f"""
                SELECT r.id, r.run_uuid, r.stage, r.status, r.params,
                       r.started_at, r.finished_at, r.error_message,
                       b.name AS backend, d.name AS design, d.pdk
                FROM runs r
                JOIN backends b ON b.id = r.backend_id
                JOIN designs  d ON d.id = r.design_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_run(
        db: Any,
        run_id: int,
    ) -> dict[str, Any] | None:
        row = db.execute(
            text(
                """
                SELECT r.*, b.name AS backend, d.name AS design, d.pdk
                FROM runs r
                JOIN backends b ON b.id = r.backend_id
                JOIN designs  d ON d.id = r.design_id
                WHERE r.id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()
        return dict(row) if row else None

    @staticmethod
    def get_session_trace(
        db: Any,
        session_id: int,
        *,
        stage: str | None = None,
        from_seq: int | None = None,
        to_seq: int | None = None,
        human_approved: bool | None = None,
    ) -> dict[str, Any]:
        """Return the full lineage trace for a session.

        Optional filters:
            stage           – include only runs/outcomes matching this stage name.
            from_seq/to_seq – include only runs with stage_seq in [from_seq, to_seq].
            human_approved  – when True/False, filter decision_trace rows accordingly.
        """
        session_row = db.execute(
            text(
                """
                SELECT fs.id, fs.session_uuid, fs.design_id, fs.objective, fs.status,
                       fs.baseline_run_id, fs.parent_session_id,
                       fs.last_inference_id, fs.last_case_id, fs.last_rule_id,
                       fs.env_snapshot, fs.notes, fs.created_at, fs.updated_at,
                       d.name AS design_name, d.pdk
                FROM flow_sessions fs
                JOIN designs d ON d.id = fs.design_id
                WHERE fs.id = :session_id
                """
            ),
            {"session_id": session_id},
        ).mappings().first()

        if not session_row:
            return {"error": f"Session {session_id} not found"}

        # Build dynamic WHERE clauses for runs
        run_filters = ["r.session_id = :session_id"]
        run_params: dict[str, Any] = {"session_id": session_id}
        if stage:
            run_filters.append("r.stage = :stage")
            run_params["stage"] = stage
        if from_seq is not None:
            run_filters.append("r.stage_seq >= :from_seq")
            run_params["from_seq"] = from_seq
        if to_seq is not None:
            run_filters.append("r.stage_seq <= :to_seq")
            run_params["to_seq"] = to_seq
        run_where = " AND ".join(run_filters)

        runs = db.execute(
            text(
                f"""
                SELECT r.id, r.run_uuid, r.stage, r.stage_seq, r.variant_tag,
                       r.rerun_reason, r.is_baseline, r.is_selected,
                       r.parent_run_id, r.status, r.started_at, r.finished_at,
                       r.created_at
                FROM runs r
                WHERE {run_where}
                ORDER BY r.stage_seq ASC, r.created_at ASC
                """
            ),
            run_params,
        ).mappings().fetchall()

        # stage_outcomes follow the same run filter
        outcome_filters = ["r.session_id = :session_id"]
        outcome_params: dict[str, Any] = {"session_id": session_id}
        if stage:
            outcome_filters.append("so.stage_name = :stage")
            outcome_params["stage"] = stage
        if from_seq is not None:
            outcome_filters.append("r.stage_seq >= :from_seq")
            outcome_params["from_seq"] = from_seq
        if to_seq is not None:
            outcome_filters.append("r.stage_seq <= :to_seq")
            outcome_params["to_seq"] = to_seq
        outcome_where = " AND ".join(outcome_filters)

        stage_outcomes = db.execute(
            text(
                f"""
                SELECT so.id, so.run_id, so.stage_name, so.status,
                       so.started_at, so.finished_at,
                       so.input_params_snapshot, so.output_metrics_snapshot,
                       so.artifact_refs, so.root_cause_inference_id,
                       so.recommendation, so.approval_status, so.created_at
                FROM stage_outcomes so
                JOIN runs r ON r.id = so.run_id
                WHERE {outcome_where}
                ORDER BY so.created_at ASC
                """
            ),
            outcome_params,
        ).mappings().fetchall()

        # decision_trace filter
        dt_filters = ["session_id = :session_id"]
        dt_params: dict[str, Any] = {"session_id": session_id}
        if human_approved is not None:
            dt_filters.append("human_approved = :human_approved")
            dt_params["human_approved"] = human_approved
        dt_where = " AND ".join(dt_filters)

        decisions = db.execute(
            text(
                f"""
                SELECT id, session_id, source_run_id, target_run_id,
                       inference_id, case_id, rule_id,
                       llm_reason, llm_reason_structured, human_approved, created_at
                FROM decision_trace
                WHERE {dt_where}
                ORDER BY created_at ASC
                """
            ),
            dt_params,
        ).mappings().fetchall()

        return {
            "session": dict(session_row),
            "runs": [dict(r) for r in runs],
            "stage_outcomes": [dict(r) for r in stage_outcomes],
            "decision_trace": [dict(r) for r in decisions],
        }
