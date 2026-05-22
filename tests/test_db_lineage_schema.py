from __future__ import annotations

from eda_agent.db.schema import Base, DecisionTrace, FlowSession, Run, StageOutcome


def test_lineage_tables_registered_in_metadata():
    assert "flow_sessions" in Base.metadata.tables
    assert "stage_outcomes" in Base.metadata.tables
    assert "decision_trace" in Base.metadata.tables


def test_run_has_session_lineage_columns_and_indexes():
    assert Run.__table__.c.session_id.nullable is True
    assert Run.__table__.c.stage_seq.nullable is False
    assert Run.__table__.c.variant_tag.nullable is False
    assert Run.__table__.c.rerun_reason.nullable is False
    assert Run.__table__.c.is_baseline.nullable is False
    assert Run.__table__.c.is_selected.nullable is False

    index_names = {index.name for index in Run.__table__.indexes}
    assert "ix_runs_session_id" in index_names
    assert "ix_runs_parent_run_id" in index_names
    assert "ix_runs_session_stage" in index_names


def test_stage_outcome_and_decision_trace_columns():
    assert StageOutcome.__table__.c.run_id.nullable is False
    assert StageOutcome.__table__.c.root_cause_inference_id.nullable is True
    assert DecisionTrace.__table__.c.session_id.nullable is False
    assert DecisionTrace.__table__.c.source_run_id.nullable is False
    assert DecisionTrace.__table__.c.target_run_id.nullable is False
    assert DecisionTrace.__table__.c.inference_id.nullable is True
    assert DecisionTrace.__table__.c.case_id.nullable is True
    assert DecisionTrace.__table__.c.rule_id.nullable is True
    assert "llm_reason_structured" in {c.name for c in DecisionTrace.__table__.columns}
    assert DecisionTrace.__table__.c.llm_reason_structured.nullable is True


def test_flow_session_relationships_exist():
    assert FlowSession.__table__.c.session_uuid.unique is True
    assert FlowSession.__table__.c.design_id.nullable is False
    assert FlowSession.__table__.c.baseline_run_id.nullable is True
    assert FlowSession.__table__.c.parent_session_id.nullable is True


def test_flow_session_env_snapshot_and_inference_context_columns():
    cols = {c.name for c in FlowSession.__table__.columns}
    assert "env_snapshot" in cols
    assert "last_inference_id" in cols
    assert "last_case_id" in cols
    assert "last_rule_id" in cols
    assert FlowSession.__table__.c.env_snapshot.nullable is True
