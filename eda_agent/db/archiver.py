"""Parquet archiver – exports PostgreSQL data to partitioned Parquet files.

Partition layout::

    {PARQUET_ARCHIVE_DIR}/
        backend={backend_name}/
            design={design_name}/
                year={YYYY}/
                    month={MM}/
                        runs_{timestamp}.parquet
                        timing_summary_{timestamp}.parquet
                        timing_paths_{timestamp}.parquet
                        congestion_hotspots_{timestamp}.parquet

Usage::

    from eda_agent.db.archiver import archive_run

    archive_run(run_id=42)   # archives all tables for a single run
    archive_all()            # archives everything since last archive
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

from eda_agent.config import settings
from eda_agent.db.session import get_db

logger = logging.getLogger(__name__)


def _partition_path(
    base_dir: Path,
    backend_name: str,
    design_name: str,
    dt: datetime,
) -> Path:
    return (
        base_dir
        / f"backend={backend_name}"
        / f"design={design_name}"
        / f"year={dt.year:04d}"
        / f"month={dt.month:02d}"
    )


def archive_run(run_id: int, archive_dir: Path | None = None) -> dict[str, Path]:
    """Export all data for *run_id* to Parquet files.

    Returns a mapping ``table_name → parquet_path``.
    """
    base_dir = archive_dir or settings.parquet_archive_dir
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    written: dict[str, Path] = {}

    with get_db() as db:
        # Fetch run metadata
        row = db.execute(
            text(
                """
                SELECT r.run_uuid, r.stage, r.created_at,
                       b.name AS backend_name, d.name AS design_name
                FROM runs r
                JOIN backends b ON b.id = r.backend_id
                JOIN designs  d ON d.id = r.design_id
                WHERE r.id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().first()

        if row is None:
            raise ValueError(f"Run id={run_id} not found.")

        out_dir = _partition_path(
            base_dir,
            row["backend_name"],
            row["design_name"],
            row["created_at"],
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        def _write(table: str, query: str, params: dict) -> Path:
            df = pd.read_sql(text(query), db.bind, params=params)
            path = out_dir / f"{table}_{ts}.parquet"
            df.to_parquet(path, index=False, engine="pyarrow")
            logger.info("Archived %d rows → %s", len(df), path)
            return path

        written["runs"] = _write(
            "runs",
            "SELECT * FROM runs WHERE id = :run_id",
            {"run_id": run_id},
        )
        written["timing_summary"] = _write(
            "timing_summary",
            "SELECT * FROM timing_summary WHERE run_id = :run_id",
            {"run_id": run_id},
        )
        written["timing_paths"] = _write(
            "timing_paths",
            "SELECT * FROM timing_paths WHERE run_id = :run_id",
            {"run_id": run_id},
        )
        # Congestion hotspots: export WKT text (geometry not directly parquet-able)
        written["congestion_hotspots"] = _write(
            "congestion_hotspots",
            """
            SELECT id, run_id, overflow, layer, created_at,
                   ST_AsText(geom) AS geom_wkt
            FROM congestion_hotspots
            WHERE run_id = :run_id
            """,
            {"run_id": run_id},
        )

    return written


def archive_all(since: datetime | None = None, archive_dir: Path | None = None) -> int:
    """Archive all runs (optionally since *since*).

    Returns the number of runs archived.
    """
    with get_db() as db:
        query = "SELECT id FROM runs"
        params: dict[str, Any] = {}
        if since is not None:
            query += " WHERE created_at >= :since"
            params["since"] = since
        run_ids = [r[0] for r in db.execute(text(query), params).fetchall()]

    count = 0
    for run_id in run_ids:
        try:
            archive_run(run_id, archive_dir=archive_dir)
            count += 1
        except Exception:
            logger.exception("Failed to archive run %d", run_id)
    return count
