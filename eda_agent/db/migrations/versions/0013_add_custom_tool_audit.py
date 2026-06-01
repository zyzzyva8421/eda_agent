"""Add custom_tool_audit table for user-defined tool execution logs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from eda_agent.db.json_type import JSON_OR_JSONB

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "custom_tool_audit",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("source", sa.String(256), nullable=False, server_default=""),
        sa.Column(
            "arguments_summary",
            JSON_OR_JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("exit_code", sa.Integer),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("error_message", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_custom_tool_audit_tool_name", "custom_tool_audit", ["tool_name"]
    )
    op.create_index(
        "ix_custom_tool_audit_created_at", "custom_tool_audit", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_custom_tool_audit_created_at", table_name="custom_tool_audit")
    op.drop_index("ix_custom_tool_audit_tool_name", table_name="custom_tool_audit")
    op.drop_table("custom_tool_audit")
