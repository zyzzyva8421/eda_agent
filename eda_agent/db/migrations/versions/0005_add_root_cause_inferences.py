"""Add root_cause_inferences table for Phase A inference engine.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "root_cause_inferences",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("symptoms", sa.Text, nullable=False, server_default=""),
        sa.Column("features", JSONB, nullable=False, server_default="{}"),
        sa.Column("hypotheses", JSONB, nullable=False, server_default="[]"),
        sa.Column("chosen_cause", sa.String(256), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_root_cause_inferences_run_id", "root_cause_inferences", ["run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_root_cause_inferences_run_id", table_name="root_cause_inferences")
    op.drop_table("root_cause_inferences")
