"""Add rule_weights table for Phase B feedback learning.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_weights",
        sa.Column("rule_id", sa.String(128), primary_key=True),
        sa.Column(
            "multiplier",
            sa.Float,
            nullable=False,
            server_default="1.0",
        ),
        sa.Column(
            "confirm_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("rule_weights")
