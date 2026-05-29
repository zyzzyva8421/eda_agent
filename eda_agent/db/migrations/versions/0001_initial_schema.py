"""Initial schema – backends, designs, runs, timing, congestion, artifacts.

Revision ID: 0001
Revises:
Create Date: 2026-04-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from eda_agent.db.json_type import JSON_OR_JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "backends",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("version", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "designs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("pdk", sa.String(128), nullable=False, server_default=""),
        sa.Column("config_path", sa.Text, nullable=False, server_default=""),
        sa.Column("rtl_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", "pdk", name="uq_design_name_pdk"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "backend_id",
            sa.Integer,
            sa.ForeignKey("backends.id"),
            nullable=False,
        ),
        sa.Column(
            "design_id",
            sa.Integer,
            sa.ForeignKey("designs.id"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("params", JSON_OR_JSONB, nullable=False, server_default="{}"),
        sa.Column("git_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column("log_path", sa.Text, nullable=False, server_default=""),
        sa.Column("report_dir", sa.Text, nullable=False, server_default=""),
        sa.Column("error_message", sa.Text, nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_runs_backend_design_stage", "runs", ["backend_id", "design_id", "stage"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])

    op.create_table(
        "timing_summary",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("view", sa.String(128), nullable=False, server_default="default"),
        sa.Column("wns_ns", sa.Float),
        sa.Column("tns_ns", sa.Float),
        sa.Column("failing_endpoints", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_timing_summary_run_id", "timing_summary", ["run_id"])
    op.create_index("ix_timing_summary_wns", "timing_summary", ["wns_ns"])

    op.create_table(
        "timing_paths",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("startpoint", sa.Text, nullable=False, server_default=""),
        sa.Column("endpoint", sa.Text, nullable=False, server_default=""),
        sa.Column("path_group", sa.String(256)),
        sa.Column("slack_ns", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_timing_paths_run_id", "timing_paths", ["run_id"])
    op.create_index("ix_timing_paths_slack", "timing_paths", ["slack_ns"])

    op.create_table(
        "congestion_hotspots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", Geometry(geometry_type="POLYGON", srid=0), nullable=False),
        sa.Column("overflow", sa.Integer, nullable=False, server_default="0"),
        sa.Column("layer", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_congestion_hotspots_run_id", "congestion_hotspots", ["run_id"])
    op.create_index(
        "ix_congestion_hotspots_geom",
        "congestion_hotspots",
        ["geom"],
        postgresql_using="gist",
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("file_size_bytes", sa.BigInteger),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    # Seed built-in backends
    bind = op.get_bind()
    if _supports_postgresql_on_conflict(bind):
        op.execute(
            """
            INSERT INTO backends (name, version, is_active) VALUES
                ('orfs',    'unknown', true),
                ('innovus', 'stub',    false),
                ('icc2',    'stub',    false)
            ON CONFLICT (name) DO NOTHING
            """
        )
    else:
        op.execute(
            """
            INSERT INTO backends (name, version, is_active)
            SELECT seed.name, seed.version, seed.is_active
            FROM (
                VALUES
                    ('orfs',    'unknown', true),
                    ('innovus', 'stub',    false),
                    ('icc2',    'stub',    false)
            ) AS seed(name, version, is_active)
            WHERE NOT EXISTS (
                SELECT 1
                FROM backends existing
                WHERE existing.name = seed.name
            )
            """
        )


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("congestion_hotspots")
    op.drop_table("timing_paths")
    op.drop_table("timing_summary")
    op.drop_table("runs")
    op.drop_table("users")
    op.drop_table("designs")
    op.drop_table("backends")


def _supports_postgresql_on_conflict(bind) -> bool:
    """Return True when current PostgreSQL server version supports ON CONFLICT."""
    ver_info = getattr(bind.dialect, "server_version_info", None)
    if isinstance(ver_info, tuple) and len(ver_info) >= 2:
        return (int(ver_info[0]), int(ver_info[1])) >= (9, 5)

    try:
        ver_num = bind.execute(sa.text("SHOW server_version_num")).scalar()
        return int(ver_num) >= 90500
    except Exception:
        return False
