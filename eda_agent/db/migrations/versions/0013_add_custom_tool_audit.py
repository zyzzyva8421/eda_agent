"""Add custom_tool_audit table for user-defined tool execution logs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_tool_audit (
            id BIGSERIAL PRIMARY KEY,
            tool_name VARCHAR(128) NOT NULL,
            source VARCHAR(256) NOT NULL DEFAULT '',
            arguments_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            exit_code INTEGER,
            ok BOOLEAN NOT NULL DEFAULT FALSE,
            error_message TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_custom_tool_audit_tool_name
        ON custom_tool_audit (tool_name)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_custom_tool_audit_created_at
        ON custom_tool_audit (created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS custom_tool_audit")
