"""Add structured reason JSON column to decision_trace.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-22
"""

import sqlalchemy as sa
from alembic import op

from eda_agent.db.json_type import JSON_OR_JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "decision_trace",
        sa.Column("llm_reason_structured", JSON_OR_JSONB, nullable=True),
    )
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql" and _supports_postgresql_jsonb(bind):
        op.execute(
            """
            UPDATE decision_trace
            SET llm_reason_structured =
                jsonb_build_object('kind', 'legacy_text', 'text', llm_reason)
            WHERE llm_reason IS NOT NULL AND llm_reason <> ''
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            UPDATE decision_trace
            SET llm_reason_structured =
                ('{"kind":"legacy_text","text":' || to_json(llm_reason)::text || '}')::json
            WHERE llm_reason IS NOT NULL AND llm_reason <> ''
            """
        )
    else:
        op.execute(
            """
            UPDATE decision_trace
            SET llm_reason_structured =
                json_object('kind', 'legacy_text', 'text', llm_reason)
            WHERE llm_reason IS NOT NULL AND llm_reason <> ''
            """
        )


def downgrade() -> None:
    op.drop_column("decision_trace", "llm_reason_structured")


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
