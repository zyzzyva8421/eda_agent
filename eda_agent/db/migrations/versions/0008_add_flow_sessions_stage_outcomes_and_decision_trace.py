"""Add flow session lineage, stage outcomes, and decision traces.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from eda_agent.db.json_type import JSON_OR_JSONB

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # flow_sessions: experiment / flow lineage root
    # ------------------------------------------------------------------
    op.create_table(
        "flow_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("design_id", sa.Integer(), sa.ForeignKey("designs.id"), nullable=False),
        sa.Column("objective", sa.String(64), nullable=False, server_default="pnr"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("baseline_run_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_session_id", sa.Integer(), sa.ForeignKey("flow_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("session_uuid", name="uq_flow_sessions_session_uuid"),
    )
    op.create_index("ix_flow_sessions_design_status", "flow_sessions", ["design_id", "status"])
    op.create_index("ix_flow_sessions_parent_session_id", "flow_sessions", ["parent_session_id"])
    op.create_index("ix_flow_sessions_baseline_run_id", "flow_sessions", ["baseline_run_id"])

    # ------------------------------------------------------------------
    # runs: bind execution rows to a lineage/session and variant metadata
    # ------------------------------------------------------------------
    op.add_column("runs", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("stage_seq", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("variant_tag", sa.String(64), nullable=False, server_default=""))
    op.add_column("runs", sa.Column("rerun_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("runs", sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("runs", sa.Column("is_selected", sa.Boolean(), nullable=False, server_default="false"))
    op.create_index("ix_runs_session_id", "runs", ["session_id"])
    op.create_index("ix_runs_session_stage", "runs", ["session_id", "stage", "created_at"])
    op.create_foreign_key(
        "fk_runs_session_id_flow_sessions",
        source_table="runs",
        referent_table="flow_sessions",
        local_cols=["session_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_flow_sessions_baseline_run_id_runs",
        source_table="flow_sessions",
        referent_table="runs",
        local_cols=["baseline_run_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # stage_outcomes: per-stage snapshots for reproducibility
    # ------------------------------------------------------------------
    op.create_table(
        "stage_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_params_snapshot", JSON_OR_JSONB, nullable=False, server_default="{}"),
        sa.Column("output_metrics_snapshot", JSON_OR_JSONB, nullable=False, server_default="{}"),
        sa.Column("artifact_refs", JSON_OR_JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "root_cause_inference_id",
            sa.Integer(),
            sa.ForeignKey("root_cause_inferences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_stage_outcomes_run_stage", "stage_outcomes", ["run_id", "stage_name"])
    op.create_index("ix_stage_outcomes_status", "stage_outcomes", ["status"])
    op.create_index("ix_stage_outcomes_created_at", "stage_outcomes", ["created_at"])
    op.create_index(
        "ix_stage_outcomes_root_cause_inference_id",
        "stage_outcomes",
        ["root_cause_inference_id"],
    )

    # ------------------------------------------------------------------
    # decision_trace: capture why a rerun was chosen
    # ------------------------------------------------------------------
    op.create_table(
        "decision_trace",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("flow_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_run_id", sa.BigInteger(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_run_id", sa.BigInteger(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "inference_id",
            sa.Integer(),
            sa.ForeignKey("root_cause_inferences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("case_memory.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rule_id",
            sa.String(128),
            sa.ForeignKey("rule_weights.rule_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("llm_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("human_approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_decision_trace_session_id", "decision_trace", ["session_id"])
    op.create_index(
        "ix_decision_trace_run_pair",
        "decision_trace",
        ["source_run_id", "target_run_id"],
    )
    op.create_index("ix_decision_trace_inference_id", "decision_trace", ["inference_id"])
    op.create_index("ix_decision_trace_case_id", "decision_trace", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_decision_trace_case_id", table_name="decision_trace")
    op.drop_index("ix_decision_trace_inference_id", table_name="decision_trace")
    op.drop_index("ix_decision_trace_run_pair", table_name="decision_trace")
    op.drop_index("ix_decision_trace_session_id", table_name="decision_trace")
    op.drop_table("decision_trace")

    op.drop_index("ix_stage_outcomes_root_cause_inference_id", table_name="stage_outcomes")
    op.drop_index("ix_stage_outcomes_created_at", table_name="stage_outcomes")
    op.drop_index("ix_stage_outcomes_status", table_name="stage_outcomes")
    op.drop_index("ix_stage_outcomes_run_stage", table_name="stage_outcomes")
    op.drop_table("stage_outcomes")

    op.drop_constraint("fk_flow_sessions_baseline_run_id_runs", "flow_sessions", type_="foreignkey")
    op.drop_constraint("fk_runs_session_id_flow_sessions", "runs", type_="foreignkey")
    op.drop_index("ix_runs_session_stage", table_name="runs")
    op.drop_index("ix_runs_session_id", table_name="runs")
    op.drop_column("runs", "is_selected")
    op.drop_column("runs", "is_baseline")
    op.drop_column("runs", "rerun_reason")
    op.drop_column("runs", "variant_tag")
    op.drop_column("runs", "stage_seq")
    op.drop_column("runs", "session_id")

    op.drop_index("ix_flow_sessions_baseline_run_id", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_parent_session_id", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_design_status", table_name="flow_sessions")
    op.drop_table("flow_sessions")
