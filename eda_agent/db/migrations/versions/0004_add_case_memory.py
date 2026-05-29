"""Add case_memory table for persistent debugging case storage.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from eda_agent.db.json_type import JSON_OR_JSONB

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_memory",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("design_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("pdk", sa.String(128), nullable=False, server_default=""),
        sa.Column("symptoms", sa.Text, nullable=False, server_default=""),
        sa.Column("root_cause", sa.Text, nullable=False, server_default=""),
        sa.Column("actions", JSON_OR_JSONB, nullable=False, server_default="[]"),
        sa.Column("result_metrics", JSON_OR_JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    # B-tree index on design_name for fast filtering
    op.create_index("ix_case_memory_design_name", "case_memory", ["design_name"])
    # GIN index on tsvector(symptoms + root_cause) for full-text search
    op.execute(
        """
        CREATE INDEX ix_case_memory_fts ON case_memory
        USING GIN (to_tsvector('english', symptoms || ' ' || root_cause))
        """
    )


def downgrade() -> None:
    op.drop_index("ix_case_memory_fts", table_name="case_memory")
    op.drop_index("ix_case_memory_design_name", table_name="case_memory")
    op.drop_table("case_memory")
