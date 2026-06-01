"""Add design targets, run hierarchy, and timing_path_stages.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── designs: target specs ──────────────────────────────────────────────
    op.add_column("designs", sa.Column("target_frequency_mhz", sa.Float(), nullable=True))
    op.add_column("designs", sa.Column("target_utilization_pct", sa.Float(), nullable=True))
    op.add_column("designs", sa.Column("voltage_v", sa.Float(), nullable=True))
    op.add_column(
        "designs",
        sa.Column(
            "design_type",
            sa.String(64),
            nullable=False,
            server_default="block",
        ),
    )

    # ── runs: hierarchical parent-child relation ───────────────────────────
    op.add_column(
        "runs",
        sa.Column(
            "parent_run_id",
            sa.BigInteger(),
            sa.ForeignKey("runs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_runs_parent_run_id", "runs", ["parent_run_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_parent_run_id", table_name="runs")
    op.drop_column("runs", "parent_run_id")
    op.drop_column("designs", "design_type")
    op.drop_column("designs", "voltage_v")
    op.drop_column("designs", "target_utilization_pct")
    op.drop_column("designs", "target_frequency_mhz")
