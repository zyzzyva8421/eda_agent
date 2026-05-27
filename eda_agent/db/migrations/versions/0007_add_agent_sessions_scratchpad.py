"""Add scratchpad JSONB column to agent_sessions.

Stores L2 session facts (design_name / pdk / config_path / last_run_id …)
so they survive process restarts alongside the OpenAI-format ``messages``
history.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-27
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
    op.add_column(
        "agent_sessions",
        sa.Column(
            "scratchpad",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "scratchpad")
