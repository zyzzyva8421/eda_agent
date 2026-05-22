"""Add structured reason JSONB column to decision_trace.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "decision_trace",
        sa.Column("llm_reason_structured", JSONB, nullable=True),
    )
    op.execute(
        """
        UPDATE decision_trace
        SET llm_reason_structured =
            jsonb_build_object('kind', 'legacy_text', 'text', llm_reason)
        WHERE llm_reason IS NOT NULL AND llm_reason <> ''
        """
    )


def downgrade() -> None:
    op.drop_column("decision_trace", "llm_reason_structured")
