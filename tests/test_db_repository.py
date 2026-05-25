"""Tests for db/repository.py – query building and result mapping."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from eda_agent.db.repository import EDAQueryRepository


# ── helpers ────────────────────────────────────────────────────────────────────


def _mock_db(rows: list[dict] | None = None, fetchall: list | None = None):
    """Return a mock session pre-configured for ``mappings().fetchall()``."""
    mock_db = MagicMock()
    if fetchall is not None:
        mock_db.execute.return_value.mappings.return_value.fetchall.return_value = fetchall
    elif rows is not None:
        mapped = [Mock(**r) for r in rows]
        mock_db.execute.return_value.mappings.return_value.fetchall.return_value = mapped
    return mock_db


# ── get_timing ──────────────────────────────────────────────────────────────────


def test_get_timing_default_params():
    db = _mock_db(
        fetchall=[],
    )
    result = EDAQueryRepository.get_timing(db, "gcd")
    assert isinstance(result, dict)
    assert "summary" in result
    assert "paths" in result


def test_get_timing_with_stage_and_run_id():
    db = _mock_db(fetchall=[])
    result = EDAQueryRepository.get_timing(
        db, "aes", stage="route", run_id=42, limit=5
    )
    assert result["summary"] == []
    assert result["paths"] == []


def test_get_timing_returns_rows():
    """dict(r) requires r to have keys(). Use a simple dict-like class."""

    class Row:
        def __init__(self, data):
            self._data = data
        def keys(self):
            return self._data.keys()
        def __getitem__(self, key):
            return self._data[key]

    s_rows = [Row({"id": 1, "run_id": 42, "stage": "route", "backend": "orfs",
                    "view": "default", "wns_ns": -0.3, "tns_ns": -5.0,
                    "failing_endpoints": 7})]
    p_rows = [Row({"id": 1, "run_id": 42, "startpoint": "u_core/a",
                    "endpoint": "u_core/b", "path_group": "clk", "slack_ns": -0.3})]
    db = Mock()
    db.execute.return_value.mappings.return_value.fetchall.side_effect = [
        s_rows, p_rows,
    ]
    result = EDAQueryRepository.get_timing(db, "gcd")
    assert len(result["summary"]) == 1
    assert result["summary"][0]["wns_ns"] == -0.3
    assert len(result["paths"]) == 1


# ── get_congestion ──────────────────────────────────────────────────────────────


def test_get_congestion_without_bbox():
    db = _mock_db(fetchall=[])
    rows = EDAQueryRepository.get_congestion(db, 42)
    assert isinstance(rows, list)


def test_get_congestion_with_bbox():
    db = _mock_db(fetchall=[])
    rows = EDAQueryRepository.get_congestion(
        db, 42, x1=0, y1=0, x2=100, y2=100
    )
    assert isinstance(rows, list)


# ── get_utilization ─────────────────────────────────────────────────────────────


def test_get_utilization():
    db = _mock_db(fetchall=[])
    rows = EDAQueryRepository.get_utilization(db, "gcd", stage="place")
    assert isinstance(rows, list)


# ── get_power ───────────────────────────────────────────────────────────────────


def test_get_power():
    db = _mock_db(fetchall=[])
    rows = EDAQueryRepository.get_power(db, "gcd", limit=5)
    assert isinstance(rows, list)


# ── compare_runs ────────────────────────────────────────────────────────────────


def test_compare_runs():
    db = Mock()
    # build a single-row mapping result
    row = {"id": 1, "stage": "route", "params": {}, "status": "success",
           "backend": "orfs", "design": "gcd",
           "wns_ns": -0.3, "tns_ns": -5.0, "failing_endpoints": 7}
    db.execute.return_value.mappings.return_value.first.return_value = row
    result = EDAQueryRepository.compare_runs(db, 1, 2)
    assert "run_a" in result
    assert "run_b" in result
    assert "delta" in result


def test_compare_runs_delta():
    """Delta is computed as run_b - run_a."""
    row_a = {"id": 1, "wns_ns": -0.5, "tns_ns": -10.0, "failing_endpoints": 10}
    row_b = {"id": 2, "wns_ns": -0.2, "tns_ns": -5.0, "failing_endpoints": 3}
    db = Mock()
    db.execute.return_value.mappings.return_value.first.side_effect = [row_a, row_b]
    result = EDAQueryRepository.compare_runs(db, 1, 2)
    assert result["delta"]["wns_ns"] == pytest.approx(0.3)  # -0.2 - (-0.5) = 0.3
    assert result["delta"]["tns_ns"] == pytest.approx(5.0)
    assert result["delta"]["failing_endpoints"] == -7  # 3 - 10 = -7


# ── get_run_log ─────────────────────────────────────────────────────────────────


def test_get_run_log_not_found():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = None
    result = EDAQueryRepository.get_run_log(db, 999)
    assert "error" in result


def test_get_run_log_no_log_path():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = {
        "log_path": "", "stage": "route", "status": "success", "design_name": "gcd",
    }
    result = EDAQueryRepository.get_run_log(db, 1)
    assert "error" in result


# ── list_runs / get_run ─────────────────────────────────────────────────────────


def test_list_runs():
    db = _mock_db(fetchall=[])
    rows = EDAQueryRepository.list_runs(db, design_name="gcd", limit=10)
    assert isinstance(rows, list)


def test_get_run_not_found():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = None
    result = EDAQueryRepository.get_run(db, 999)
    assert result is None


# ── get_session_trace ─────────────────────────────────────────────────────────


def test_get_session_trace_includes_multi_agent_structured_reason_kind():
    db = Mock()

    class _Result:
        def __init__(self, *, first=None, rows=None):
            self._first = first
            self._rows = rows or []

        def mappings(self):
            return self

        def first(self):
            return self._first

        def fetchall(self):
            return self._rows

    session_row = {
        "id": 7,
        "session_uuid": "sess-7",
        "design_id": 1,
        "objective": "tune_ppa",
        "status": "active",
        "baseline_run_id": None,
        "parent_session_id": None,
        "last_inference_id": None,
        "last_case_id": None,
        "last_rule_id": None,
        "env_snapshot": {},
        "notes": "",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "design_name": "aes",
        "pdk": "tsmc18",
    }

    run_rows = [
        {
            "id": 101,
            "run_uuid": "r-101",
            "stage": "place",
            "stage_seq": 1,
            "variant_tag": "multi_agent_experiment",
            "rerun_reason": "run_multi_agent_cycle",
            "is_baseline": False,
            "is_selected": False,
            "parent_run_id": 100,
            "status": "success",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:05:00Z",
            "created_at": "2026-01-01T00:05:00Z",
        }
    ]

    decision_rows = [
        {
            "id": 1,
            "session_id": 7,
            "source_run_id": 100,
            "target_run_id": 101,
            "inference_id": None,
            "case_id": None,
            "rule_id": None,
            "llm_reason": "multi_agent_cycle executed experiment innovus:place",
            "llm_reason_structured": {"kind": "multi_agent_cycle", "agents": ["pnr", "sta"]},
            "human_approved": False,
            "created_at": "2026-01-01T00:05:01Z",
        }
    ]

    db.execute.side_effect = [
        _Result(first=session_row),   # session query
        _Result(rows=run_rows),       # runs query
        _Result(rows=[]),             # stage_outcomes query
        _Result(rows=decision_rows),  # decision_trace query
    ]

    result = EDAQueryRepository.get_session_trace(db, 7)

    assert result["session"]["id"] == 7
    assert result["decision_trace"]
    structured = result["decision_trace"][0]["llm_reason_structured"]
    assert isinstance(structured, dict)
    assert structured.get("kind") == "multi_agent_cycle"
