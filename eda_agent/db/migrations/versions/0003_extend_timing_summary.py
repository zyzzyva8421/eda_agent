"""Add extended timing metrics to timing_summary.

Adds fmax_mhz, clock_skew_ns, max_slew_violations, max_fanout_violations,
max_cap_violations, setup_violations, hold_violations,
critical_path_delay_ns, and slack_cpd_ratio_pct columns that are parsed
by TimingParser but were previously discarded before reaching the DB.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("timing_summary", sa.Column("fmax_mhz", sa.Float, nullable=True))
    op.add_column("timing_summary", sa.Column("clock_skew_ns", sa.Float, nullable=True))
    op.add_column("timing_summary", sa.Column("max_slew_violations", sa.Integer, nullable=True))
    op.add_column("timing_summary", sa.Column("max_fanout_violations", sa.Integer, nullable=True))
    op.add_column("timing_summary", sa.Column("max_cap_violations", sa.Integer, nullable=True))
    op.add_column("timing_summary", sa.Column("setup_violations", sa.Integer, nullable=True))
    op.add_column("timing_summary", sa.Column("hold_violations", sa.Integer, nullable=True))
    op.add_column(
        "timing_summary", sa.Column("critical_path_delay_ns", sa.Float, nullable=True)
    )
    op.add_column(
        "timing_summary", sa.Column("slack_cpd_ratio_pct", sa.Float, nullable=True)
    )


def downgrade() -> None:
    for col in [
        "slack_cpd_ratio_pct",
        "critical_path_delay_ns",
        "hold_violations",
        "setup_violations",
        "max_cap_violations",
        "max_fanout_violations",
        "max_slew_violations",
        "clock_skew_ns",
        "fmax_mhz",
    ]:
        op.drop_column("timing_summary", col)
