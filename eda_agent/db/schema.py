"""SQLAlchemy ORM schema for EDA Agent.

Tables
------
backends           – registered EDA tool backends
designs            – RTL design metadata
flow_sessions      – experiment / flow lineage root for multi-stage PnR loops
runs               – individual flow stage executions
timing_summary     – per-run WNS / TNS / FEP summary
timing_paths       – individual violated timing paths
congestion_hotspots – spatial congestion hotspot polygons (PostGIS)
utilization_summary – per-run design area and cell utilisation
power_summary      – per-run power breakdown
drc_violations     – per-run DRC violation records
artifacts          – file artefacts produced by a run
agent_sessions     – persistent multi-turn agent conversation history
root_cause_inferences – per-run root cause inference results (Phase A engine)
rule_weights           – per-rule score multipliers for Phase B feedback learning
case_memory        – persisted resolved debugging cases
stage_outcomes     – per-stage execution snapshots and metrics
decision_trace     – lineage from inference to rerun decision

All spatial columns use SRID 0 (unitless chip-coordinate space).
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── backends ──────────────────────────────────────────────────────────────────

class Backend(Base):
    """EDA tool backend registration (ORFS, Innovus, ICC2, custom, …)."""

    __tablename__ = "backends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    runs: Mapped[list["Run"]] = relationship("Run", back_populates="backend")


# ── designs ───────────────────────────────────────────────────────────────────

class Design(Base):
    """Represents an RTL design (top-level module)."""

    __tablename__ = "designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    pdk: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    config_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rtl_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Design targets (used by rule engine / tuning loops)
    target_frequency_mhz: Mapped[float | None] = mapped_column(Float)
    target_utilization_pct: Mapped[float | None] = mapped_column(Float)
    voltage_v: Mapped[float | None] = mapped_column(Float)
    design_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="block"
    )  # block | chip | soc
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("name", "pdk", name="uq_design_name_pdk"),)

    runs: Mapped[list["Run"]] = relationship("Run", back_populates="design")


# ── flow_sessions ─────────────────────────────────────────────────────────────

class FlowSession(Base):
    """Experiment / flow lineage root for one baseline plus variants."""

    __tablename__ = "flow_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    design_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("designs.id"), nullable=False
    )
    objective: Mapped[str] = mapped_column(String(64), nullable=False, default="pnr")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    baseline_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    parent_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("flow_sessions.id", ondelete="SET NULL"), nullable=True
    )
    last_inference_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("root_cause_inferences.id", ondelete="SET NULL"), nullable=True
    )
    last_case_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("case_memory.id", ondelete="SET NULL"), nullable=True
    )
    last_rule_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("rule_weights.rule_id", ondelete="SET NULL"), nullable=True
    )
    env_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    design: Mapped["Design"] = relationship("Design")
    baseline_run: Mapped["Run"] = relationship(
        "Run", foreign_keys=[baseline_run_id]
    )
    parent_session: Mapped["FlowSession"] = relationship(
        "FlowSession", remote_side="FlowSession.id"
    )
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="flow_session")

    __table_args__ = (
        Index("ix_flow_sessions_last_inference_id", "last_inference_id"),
        Index("ix_flow_sessions_last_case_id", "last_case_id"),
        Index("ix_flow_sessions_last_rule_id", "last_rule_id"),
    )


# ── runs ──────────────────────────────────────────────────────────────────────

class Run(Base):
    """A single flow stage execution."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)

    backend_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backends.id"), nullable=False
    )
    design_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("designs.id"), nullable=False
    )
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("flow_sessions.id", ondelete="SET NULL"), nullable=True
    )

    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    variant_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    rerun_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # Hierarchical run relationship (multi-stage flow → parent run)
    parent_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("runs.id"), nullable=True
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    git_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    log_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    report_dir: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    backend: Mapped["Backend"] = relationship("Backend", back_populates="runs")
    design: Mapped["Design"] = relationship("Design", back_populates="runs")
    flow_session: Mapped["FlowSession"] = relationship(
        "FlowSession", back_populates="runs"
    )
    timing_summaries: Mapped[list["TimingSummary"]] = relationship(
        "TimingSummary", back_populates="run", cascade="all, delete-orphan"
    )
    timing_paths: Mapped[list["TimingPath"]] = relationship(
        "TimingPath", back_populates="run", cascade="all, delete-orphan"
    )
    congestion_hotspots: Mapped[list["CongestionHotspot"]] = relationship(
        "CongestionHotspot", back_populates="run", cascade="all, delete-orphan"
    )
    utilization_summaries: Mapped[list["UtilizationSummary"]] = relationship(
        "UtilizationSummary", back_populates="run", cascade="all, delete-orphan"
    )
    power_summaries: Mapped[list["PowerSummary"]] = relationship(
        "PowerSummary", back_populates="run", cascade="all, delete-orphan"
    )
    drc_violations: Mapped[list["DRCViolation"]] = relationship(
        "DRCViolation", back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="run", cascade="all, delete-orphan"
    )
    parent_run: Mapped["Run"] = relationship(
        "Run", remote_side="Run.id", foreign_keys=[parent_run_id]
    )

    __table_args__ = (
        Index("ix_runs_backend_design_stage", "backend_id", "design_id", "stage"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_session_id", "session_id"),
        Index("ix_runs_parent_run_id", "parent_run_id"),
        Index("ix_runs_session_stage", "session_id", "stage", "created_at"),
    )


# ── timing_summary ────────────────────────────────────────────────────────────

class TimingSummary(Base):
    """WNS / TNS / failing-endpoint-count per run and analysis view.

    Extended fields (added in migration 0003) capture additional OpenROAD
    metrics parsed by TimingParser: fmax, clock skew, violation counts, and
    critical-path delay.
    """

    __tablename__ = "timing_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    view: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    wns_ns: Mapped[float | None] = mapped_column(Float)
    tns_ns: Mapped[float | None] = mapped_column(Float)
    failing_endpoints: Mapped[int | None] = mapped_column(Integer)
    # Extended timing metrics (OpenROAD / ORFS)
    fmax_mhz: Mapped[float | None] = mapped_column(Float)
    clock_skew_ns: Mapped[float | None] = mapped_column(Float)
    max_slew_violations: Mapped[int | None] = mapped_column(Integer)
    max_fanout_violations: Mapped[int | None] = mapped_column(Integer)
    max_cap_violations: Mapped[int | None] = mapped_column(Integer)
    setup_violations: Mapped[int | None] = mapped_column(Integer)
    hold_violations: Mapped[int | None] = mapped_column(Integer)
    critical_path_delay_ns: Mapped[float | None] = mapped_column(Float)
    slack_cpd_ratio_pct: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="timing_summaries")

    __table_args__ = (
        Index("ix_timing_summary_run_id", "run_id"),
        Index("ix_timing_summary_wns", "wns_ns"),
    )


# ── timing_paths ──────────────────────────────────────────────────────────────

class TimingPath(Base):
    """Individual violated timing path extracted from a detailed path report."""

    __tablename__ = "timing_paths"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    startpoint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    path_group: Mapped[str | None] = mapped_column(String(256))
    slack_ns: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="timing_paths")

    __table_args__ = (
        Index("ix_timing_paths_run_id", "run_id"),
        Index("ix_timing_paths_slack", "slack_ns"),
    )


# ── congestion_hotspots ───────────────────────────────────────────────────────

class CongestionHotspot(Base):
    """Spatial congestion hotspot polygon (PostGIS, SRID=0)."""

    __tablename__ = "congestion_hotspots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=0), nullable=False
    )
    overflow: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    layer: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="congestion_hotspots")

    __table_args__ = (
        Index("ix_congestion_hotspots_run_id", "run_id"),
        # PostGIS spatial index
        Index(
            "ix_congestion_hotspots_geom",
            "geom",
            postgresql_using="gist",
        ),
    )


# ── artifacts ─────────────────────────────────────────────────────────────────

class Artifact(Base):
    """File artefact produced by a run (.rpt, .def, .odb, .png, …)."""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="artifacts")

    __table_args__ = (Index("ix_artifacts_run_id", "run_id"),)


# ── utilization_summary ───────────────────────────────────────────────────────

class UtilizationSummary(Base):
    """Per-run design area and cell utilisation metrics."""

    __tablename__ = "utilization_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    design_area_um2: Mapped[float | None] = mapped_column(Float)
    utilization_pct: Mapped[float | None] = mapped_column(Float)
    num_cells: Mapped[int | None] = mapped_column(Integer)
    num_registers: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="utilization_summaries")

    __table_args__ = (Index("ix_utilization_summary_run_id", "run_id"),)


# ── power_summary ─────────────────────────────────────────────────────────────

class PowerSummary(Base):
    """Per-run power breakdown (internal / switching / leakage / total), in Watts."""

    __tablename__ = "power_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    internal_power_w: Mapped[float | None] = mapped_column(Float)
    switching_power_w: Mapped[float | None] = mapped_column(Float)
    leakage_power_w: Mapped[float | None] = mapped_column(Float)
    total_power_w: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="power_summaries")

    __table_args__ = (Index("ix_power_summary_run_id", "run_id"),)


# ── drc_violations ────────────────────────────────────────────────────────────

class DRCViolation(Base):
    """Individual DRC violation records, one row per violation instance."""

    __tablename__ = "drc_violations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    # For summary records (total count line) violation_type is 'SUMMARY'
    violation_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    layer: Mapped[str | None] = mapped_column(String(64))
    nets: Mapped[list | None] = mapped_column(JSONB)
    bbox_wkt: Mapped[str | None] = mapped_column(Text)
    total_violations: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run", back_populates="drc_violations")

    __table_args__ = (Index("ix_drc_violations_run_id", "run_id"),)


# ── agent_sessions ────────────────────────────────────────────────────────────

class AgentSession(Base):
    """Persistent multi-turn agent conversation history, keyed by session_id."""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    messages: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)
    scratchpad: Mapped[dict | None] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_agent_sessions_username", "username"),)


# ── root_cause_inferences ────────────────────────────────────────────────────

class RootCauseInference(Base):
    """Stores the output of the rule-based inference engine for a single run."""

    __tablename__ = "root_cause_inferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    symptoms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Full feature vector snapshot at inference time
    features: Mapped[dict | None] = mapped_column(JSONB, nullable=False, default=dict)
    # Top-k ranked hypotheses list
    hypotheses: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)
    # Filled in by confirm()
    chosen_cause: Mapped[str | None] = mapped_column(String(256))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_root_cause_inferences_run_id", "run_id"),)


# ── rule_weights ───────────────────────────────────────────────────────────────

class RuleWeight(Base):
    """Per-rule score multiplier updated by engineer feedback (Phase B)."""

    __tablename__ = "rule_weights"

    rule_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confirm_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── case_memory ───────────────────────────────────────────────────────────────

class CaseRecord(Base):
    """Persistent debugging case memory.

    Each record captures a resolved debugging episode so future sessions can
    retrieve similar cases and bootstrap root-cause reasoning.
    """

    __tablename__ = "case_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    design_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    pdk: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # Free-text symptom description – indexed with a GIN tsvector for FTS
    symptoms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    root_cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Ordered list of action strings (tool name + key params)
    actions: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)
    # Key QoR metrics captured after the fix (e.g. wns_before, wns_after)
    result_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_case_memory_design_name", "design_name"),)


# ── stage_outcomes ───────────────────────────────────────────────────────────

class StageOutcome(Base):
    """Per-stage execution snapshot for reproducible reruns and comparisons."""

    __tablename__ = "stage_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_params_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    output_metrics_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    artifact_refs: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)
    root_cause_inference_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("root_cause_inferences.id", ondelete="SET NULL"),
        nullable=True,
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["Run"] = relationship("Run")
    root_cause_inference: Mapped["RootCauseInference"] = relationship(
        "RootCauseInference"
    )

    __table_args__ = (
        Index("ix_stage_outcomes_run_stage", "run_id", "stage_name"),
        Index("ix_stage_outcomes_status", "status"),
        Index("ix_stage_outcomes_created_at", "created_at"),
    )


# ── decision_trace ───────────────────────────────────────────────────────────

class DecisionTrace(Base):
    """Audit trail from inference to the rerun decision and confirmation."""

    __tablename__ = "decision_trace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("flow_sessions.id", ondelete="CASCADE"), nullable=False
    )
    source_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    target_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    inference_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("root_cause_inferences.id", ondelete="SET NULL"),
        nullable=True,
    )
    case_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("case_memory.id", ondelete="SET NULL"), nullable=True
    )
    rule_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("rule_weights.rule_id", ondelete="SET NULL"),
        nullable=True,
    )
    llm_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    llm_reason_structured: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    human_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["FlowSession"] = relationship("FlowSession")
    source_run: Mapped["Run"] = relationship("Run", foreign_keys=[source_run_id])
    target_run: Mapped["Run"] = relationship("Run", foreign_keys=[target_run_id])
    inference: Mapped["RootCauseInference"] = relationship("RootCauseInference")
    case_record: Mapped["CaseRecord"] = relationship("CaseRecord")

    __table_args__ = (
        Index("ix_decision_trace_session_id", "session_id"),
        Index("ix_decision_trace_run_pair", "source_run_id", "target_run_id"),
        Index("ix_decision_trace_inference_id", "inference_id"),
    )


# ── users (for API auth) ──────────────────────────────────────────────────────

class User(Base):
    """API user for multi-user access control."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
