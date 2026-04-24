"""Add utilization_summary, power_summary, drc_violations, agent_sessions tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "utilization_summary",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("design_area_um2", sa.Float),
        sa.Column("utilization_pct", sa.Float),
        sa.Column("num_cells", sa.Integer),
        sa.Column("num_registers", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_utilization_summary_run_id", "utilization_summary", ["run_id"])

    op.create_table(
        "power_summary",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("internal_power_w", sa.Float),
        sa.Column("switching_power_w", sa.Float),
        sa.Column("leakage_power_w", sa.Float),
        sa.Column("total_power_w", sa.Float),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_power_summary_run_id", "power_summary", ["run_id"])

    op.create_table(
        "drc_violations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("violation_type", sa.String(128), nullable=False, server_default=""),
        sa.Column("layer", sa.String(64)),
        sa.Column("nets", sa.dialects.postgresql.JSONB),
        sa.Column("bbox_wkt", sa.Text),
        sa.Column("total_violations", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_drc_violations_run_id", "drc_violations", ["run_id"])

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(256), nullable=False, unique=True),
        sa.Column("username", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "messages",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_agent_sessions_username", "agent_sessions", ["username"])


def downgrade() -> None:
    op.drop_table("agent_sessions")
    op.drop_table("drc_violations")
    op.drop_table("power_summary")
    op.drop_table("utilization_summary")
