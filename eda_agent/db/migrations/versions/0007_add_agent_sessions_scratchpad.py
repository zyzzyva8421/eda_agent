"""Add scratchpad JSONB column to agent_sessions.

Stores L2 session facts (design_name / pdk / config_path / last_run_id …)
so they survive process restarts alongside the OpenAI-format ``messages``
history.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_sessions
        ADD COLUMN IF NOT EXISTS scratchpad jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_sessions
        DROP COLUMN IF EXISTS scratchpad
        """
    )
