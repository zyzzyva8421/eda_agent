"""Implementation helpers for DB persistence of runs/artifacts/parsed records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from eda_agent.backends.base import DesignSpec
from eda_agent.config import settings
from eda_agent.db.session import get_db


def upsert_run_impl(
    result: Any,
    design: DesignSpec,
    db: Any,
    run_context: dict[str, Any] | None = None,
) -> int:
    """Persist a RunResult using an active *db* session."""
    backend_row = db.execute(
        text("SELECT id FROM backends WHERE name = :name"),
        {"name": result.backend_name},
    ).first()
    backend_id = backend_row[0] if backend_row else None
    if backend_id is None:
        db.execute(
            text("INSERT INTO backends (name, version) VALUES (:name, :ver)"),
            {"name": result.backend_name, "ver": "unknown"},
        )
        backend_id = db.execute(
            text("SELECT id FROM backends WHERE name = :name"),
            {"name": result.backend_name},
        ).scalar()

    design_row = db.execute(
        text("SELECT id FROM designs WHERE name = :name AND pdk = :pdk"),
        {"name": design.name, "pdk": design.pdk},
    ).first()
    design_id = design_row[0] if design_row else None
    if design_id is None:
        db.execute(
            text(
                "INSERT INTO designs (name, pdk, config_path) "
                "VALUES (:name, :pdk, :cfg)"
            ),
            {"name": design.name, "pdk": design.pdk, "cfg": str(design.config_path)},
        )
        design_id = db.execute(
            text("SELECT id FROM designs WHERE name = :name AND pdk = :pdk"),
            {"name": design.name, "pdk": design.pdk},
        ).scalar()

    ctx = run_context or {}

    db.execute(
        text(
            """
            INSERT INTO runs
                (run_uuid, backend_id, design_id, session_id, stage, stage_seq,
                 variant_tag, rerun_reason, is_baseline, is_selected,
                 parent_run_id, status, params, log_path, report_dir,
                 error_message, started_at, finished_at)
            VALUES
                (:uuid, :bid, :did, :sid, :stage, :stage_seq,
                 :variant_tag, :rerun_reason, :is_baseline, :is_selected,
                 :parent_run_id, :status, :params, :log_path, :report_dir,
                 :error, :started, :finished)
            """
        ),
        {
            "uuid": result.run_id,
            "bid": backend_id,
            "did": design_id,
            "sid": ctx.get("session_id"),
            "stage": result.stage,
            "stage_seq": int(ctx.get("stage_seq", 0) or 0),
            "variant_tag": str(ctx.get("variant_tag", "") or ""),
            "rerun_reason": str(ctx.get("rerun_reason", "") or ""),
            "is_baseline": bool(ctx.get("is_baseline", False)),
            "is_selected": bool(ctx.get("is_selected", False)),
            "parent_run_id": ctx.get("parent_run_id"),
            "status": result.status.value,
            "params": json.dumps(result.params),
            "log_path": str(result.log_path or ""),
            "report_dir": str(result.report_dir or ""),
            "error": result.error_message,
            "started": result.started_at,
            "finished": result.finished_at,
        },
    )
    run_id = db.execute(
        text("SELECT id FROM runs WHERE run_uuid = :uuid"),
        {"uuid": result.run_id},
    ).scalar()
    return run_id


def upsert_run(
    result: Any,
    design: DesignSpec,
    db: Any = None,
    run_context: dict[str, Any] | None = None,
    get_db_fn: Any = get_db,
) -> int:
    """Insert RunResult and return integer PK.

    If *db* is provided caller manages transaction; otherwise uses its own session.
    """
    if db is not None:
        return upsert_run_impl(result, design, db, run_context=run_context)

    with get_db_fn() as session:
        return upsert_run_impl(result, design, session, run_context=run_context)


def upsert_artifacts_impl(run_id: int, reports: list[Any], db: Any) -> None:
    """Internal: persist artifacts using an active *db* session."""
    for rpt in reports:
        path = Path(str(rpt.path))
        file_size = path.stat().st_size if path.exists() else None
        db.execute(
            text(
                """
                INSERT INTO artifacts (run_id, file_path, artifact_type, file_size_bytes)
                VALUES (:run_id, :file_path, :artifact_type, :file_size_bytes)
                """
            ),
            {
                "run_id": run_id,
                "file_path": str(path),
                "artifact_type": str(getattr(rpt, "report_type", "generic")),
                "file_size_bytes": file_size,
            },
        )


def upsert_artifacts(
    run_id: int,
    reports: list[Any],
    db: Any = None,
    get_db_fn: Any = get_db,
) -> None:
    """Persist collected report files into artifacts table (best effort)."""
    if db is not None:
        upsert_artifacts_impl(run_id, reports, db)
        return
    with get_db_fn() as session:
        upsert_artifacts_impl(run_id, reports, session)


def ingest_records_impl(records: list[dict], run_id: int, stage: str, db: Any) -> None:
    """Fan out parsed records using an active *db* session."""
    for rec in records:
        kind = rec.get("kind")
        if kind == "summary" and "wns_ns" in rec:
            db.execute(
                text(
                    "INSERT INTO timing_summary "
                    "(run_id, view, wns_ns, tns_ns, failing_endpoints, "
                    " fmax_mhz, clock_skew_ns, max_slew_violations, "
                    " max_fanout_violations, max_cap_violations, "
                    " setup_violations, hold_violations, "
                    " critical_path_delay_ns, slack_cpd_ratio_pct) "
                    "VALUES (:run_id, :view, :wns, :tns, :fep, "
                    " :fmax, :skew, :slew_vio, :fanout_vio, :cap_vio, "
                    " :setup_vio, :hold_vio, :cpd, :ratio)"
                ),
                {
                    "run_id": run_id,
                    "view": rec.get("view", "default"),
                    "wns": rec.get("wns_ns"),
                    "tns": rec.get("tns_ns"),
                    "fep": rec.get("failing_endpoints"),
                    "fmax": rec.get("fmax_mhz"),
                    "skew": rec.get("clock_skew_ns"),
                    "slew_vio": rec.get("max_slew_violations"),
                    "fanout_vio": rec.get("max_fanout_violations"),
                    "cap_vio": rec.get("max_cap_violations"),
                    "setup_vio": rec.get("setup_violations"),
                    "hold_vio": rec.get("hold_violations"),
                    "cpd": rec.get("critical_path_delay_ns"),
                    "ratio": rec.get("slack_cpd_ratio_pct"),
                },
            )
        elif kind == "path":
            db.execute(
                text(
                    "INSERT INTO timing_paths "
                    "(run_id, startpoint, endpoint, path_group, slack_ns) "
                    "VALUES (:run_id, :sp, :ep, :pg, :slack)"
                ),
                {
                    "run_id": run_id,
                    "sp": rec.get("startpoint", ""),
                    "ep": rec.get("endpoint", ""),
                    "pg": rec.get("path_group"),
                    "slack": rec.get("slack_ns", 0.0),
                },
            )
        elif kind == "hotspot":
            if settings.enable_postgis:
                db.execute(
                    text(
                        "INSERT INTO congestion_hotspots "
                        "(run_id, geom, overflow) "
                        "VALUES (:run_id, ST_GeomFromText(:wkt, 0), :overflow)"
                    ),
                    {
                        "run_id": run_id,
                        "wkt": rec["wkt"],
                        "overflow": rec.get("overflow", 0),
                    },
                )
            else:
                db.execute(
                    text(
                        "INSERT INTO congestion_hotspots "
                        "(run_id, geom, overflow) "
                        "VALUES (:run_id, :wkt, :overflow)"
                    ),
                    {
                        "run_id": run_id,
                        "wkt": rec["wkt"],
                        "overflow": rec.get("overflow", 0),
                    },
                )
        elif kind == "orfs_violation":
            wkt = rec.get("wkt")
            if not wkt:
                continue
            if settings.enable_postgis:
                db.execute(
                    text(
                        "INSERT INTO congestion_hotspots "
                        "(run_id, geom, overflow, layer) "
                        "VALUES (:run_id, ST_GeomFromText(:wkt, 0), :overflow, :layer)"
                    ),
                    {
                        "run_id": run_id,
                        "wkt": wkt,
                        "overflow": rec.get("overflow", 0),
                        "layer": rec.get("layer"),
                    },
                )
            else:
                db.execute(
                    text(
                        "INSERT INTO congestion_hotspots "
                        "(run_id, geom, overflow, layer) "
                        "VALUES (:run_id, :wkt, :overflow, :layer)"
                    ),
                    {
                        "run_id": run_id,
                        "wkt": wkt,
                        "overflow": rec.get("overflow", 0),
                        "layer": rec.get("layer"),
                    },
                )
        elif kind == "summary" and "design_area_um2" in rec:
            db.execute(
                text(
                    "INSERT INTO utilization_summary "
                    "(run_id, design_area_um2, utilization_pct, num_cells, num_registers) "
                    "VALUES (:run_id, :area, :util, :cells, :regs)"
                ),
                {
                    "run_id": run_id,
                    "area": rec.get("design_area_um2"),
                    "util": rec.get("utilization_pct"),
                    "cells": rec.get("num_cells"),
                    "regs": rec.get("num_registers"),
                },
            )
        elif kind == "summary" and "total_power_w" in rec:
            db.execute(
                text(
                    "INSERT INTO power_summary "
                    "(run_id, internal_power_w, switching_power_w, "
                    "leakage_power_w, total_power_w) "
                    "VALUES (:run_id, :int, :sw, :lk, :tot)"
                ),
                {
                    "run_id": run_id,
                    "int": rec.get("internal_power_w"),
                    "sw": rec.get("switching_power_w"),
                    "lk": rec.get("leakage_power_w"),
                    "tot": rec.get("total_power_w"),
                },
            )
        elif kind == "summary" and "total_violations" in rec:
            db.execute(
                text(
                    "INSERT INTO drc_violations "
                    "(run_id, violation_type, total_violations) "
                    "VALUES (:run_id, 'SUMMARY', :total)"
                ),
                {"run_id": run_id, "total": rec.get("total_violations")},
            )
        elif kind == "drc_violation":
            db.execute(
                text(
                    "INSERT INTO drc_violations "
                    "(run_id, violation_type, layer, nets, bbox_wkt) "
                    "VALUES (:run_id, :vtype, :layer, :nets, :bbox)"
                ),
                {
                    "run_id": run_id,
                    "vtype": rec.get("violation_type", ""),
                    "layer": rec.get("layer"),
                    "nets": json.dumps(rec.get("nets") or []),
                    "bbox": rec.get("bbox_wkt"),
                },
            )


def ingest_records(
    records: list[dict],
    run_id: int,
    stage: str,
    db: Any = None,
    get_db_fn: Any = get_db,
) -> None:
    """Fan out parsed records into appropriate DB tables."""
    if db is not None:
        ingest_records_impl(records, run_id, stage, db)
        return
    with get_db_fn() as session:
        ingest_records_impl(records, run_id, stage, session)
