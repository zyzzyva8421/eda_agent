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
    bind = op.get_bind()
    op.add_column(
        "flow_sessions",
        sa.Column("env_snapshot", JSON_OR_JSONB, nullable=True),
    )
    if bind.dialect.name != "postgresql" or _supports_postgresql_jsonb(bind):
        op.create_index(
            "ix_flow_sessions_env_snapshot_gin",
            "flow_sessions",
            ["env_snapshot"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or _supports_postgresql_jsonb(bind):
        op.drop_index("ix_flow_sessions_env_snapshot_gin", table_name="flow_sessions")
    op.drop_column("flow_sessions", "env_snapshot")


def _supports_postgresql_jsonb(bind) -> bool:
    """Return True when current PostgreSQL server version supports JSONB."""
    ver_info = getattr(bind.dialect, "server_version_info", None)
    if isinstance(ver_info, tuple) and len(ver_info) >= 2:
        return (int(ver_info[0]), int(ver_info[1])) >= (9, 4)

    try:
        ver_num = bind.execute(sa.text("SHOW server_version_num")).scalar()
        return int(ver_num) >= 90400
    except Exception:
        return False
