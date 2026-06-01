"""Add inference context fields to flow_sessions.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flow_sessions", sa.Column("last_inference_id", sa.Integer(), nullable=True))
    op.add_column("flow_sessions", sa.Column("last_case_id", sa.Integer(), nullable=True))
    op.add_column("flow_sessions", sa.Column("last_rule_id", sa.String(length=128), nullable=True))

    op.create_foreign_key(
        "fk_flow_sessions_last_inference_id_root_cause_inferences",
        source_table="flow_sessions",
        referent_table="root_cause_inferences",
        local_cols=["last_inference_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_flow_sessions_last_case_id_case_memory",
        source_table="flow_sessions",
        referent_table="case_memory",
        local_cols=["last_case_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_flow_sessions_last_rule_id_rule_weights",
        source_table="flow_sessions",
        referent_table="rule_weights",
        local_cols=["last_rule_id"],
        remote_cols=["rule_id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_flow_sessions_last_inference_id", "flow_sessions", ["last_inference_id"])
    op.create_index("ix_flow_sessions_last_case_id", "flow_sessions", ["last_case_id"])
    op.create_index("ix_flow_sessions_last_rule_id", "flow_sessions", ["last_rule_id"])


def downgrade() -> None:
    op.drop_index("ix_flow_sessions_last_rule_id", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_last_case_id", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_last_inference_id", table_name="flow_sessions")

    op.drop_constraint(
        "fk_flow_sessions_last_rule_id_rule_weights",
        "flow_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_flow_sessions_last_case_id_case_memory",
        "flow_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_flow_sessions_last_inference_id_root_cause_inferences",
        "flow_sessions",
        type_="foreignkey",
    )

    op.drop_column("flow_sessions", "last_rule_id")
    op.drop_column("flow_sessions", "last_case_id")
    op.drop_column("flow_sessions", "last_inference_id")
