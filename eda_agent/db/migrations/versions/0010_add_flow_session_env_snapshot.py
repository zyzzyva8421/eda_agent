"""Add env_snapshot JSONB column to flow_sessions for reproducibility.

Stores toolchain versions (Python, SQLAlchemy, backend tool) and PDK at
session creation time so a run can be reproduced exactly.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa
from eda_agent.db.json_type import JSON_OR_JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_sessions",
        sa.Column("env_snapshot", JSON_OR_JSONB, nullable=True),
    )
    op.create_index(
        "ix_flow_sessions_env_snapshot_gin",
        "flow_sessions",
        ["env_snapshot"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_flow_sessions_env_snapshot_gin", table_name="flow_sessions")
    op.drop_column("flow_sessions", "env_snapshot")
