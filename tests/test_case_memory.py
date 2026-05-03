"""Tests for eda_agent.agent.memory – save_case() and search_similar_cases().

All DB calls are mocked so no PostgreSQL connection is required.
The AgentMemory class itself is tested in test_agent_memory.py; this file
focuses on the persistent case memory module-level functions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from eda_agent.agent.memory import save_case, search_similar_cases


# ── Helpers ───────────────────────────────────────────────────────────────────


# get_db is imported locally inside save_case / search_similar_cases, so the
# correct patch target is the canonical location: eda_agent.db.session.get_db
_PATCH_GET_DB = "eda_agent.db.session.get_db"


def _make_ctx(return_value=None):
    """Build a mock get_db() context manager."""
    mock_db = MagicMock()
    if return_value is not None:
        mock_row = MagicMock()
        # Support row[0] → case_id for INSERT RETURNING
        mock_row.__getitem__ = MagicMock(return_value=return_value)
        mock_db.execute.return_value.first.return_value = mock_row
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_db


def _search_rows(cases: list[dict]) -> list[tuple]:
    """Convert list[dict] to tuples matching the SELECT column order:
    id, design_name, pdk, symptoms, root_cause, actions, result_metrics, created_at.
    """
    return [
        (
            c.get("id", 1),
            c.get("design_name", "gcd"),
            c.get("pdk", "sky130hd"),
            c.get("symptoms", ""),
            c.get("root_cause", ""),
            json.dumps(c.get("actions", [])),
            json.dumps(c.get("result_metrics", {})),
            "2026-01-01T00:00:00",
        )
        for c in cases
    ]


# ── save_case ─────────────────────────────────────────────────────────────────


class TestSaveCase:
    def test_returns_case_id(self):
        ctx, _ = _make_ctx(return_value=42)
        with patch(_PATCH_GET_DB, return_value=ctx):
            case_id = save_case(
                design_name="gcd",
                symptoms="wns is -0.5",
                root_cause="routing_detour",
            )
        assert case_id == 42

    def test_passes_correct_params_to_db(self):
        ctx, mock_db = _make_ctx(return_value=1)
        with patch(_PATCH_GET_DB, return_value=ctx):
            save_case(
                design_name="aes",
                symptoms="hold violations",
                root_cause="cts_skew",
                pdk="gf180mcuD",
                actions=["fix CTS"],
                result_metrics={"wns": 0.0},
            )
        # Should call db.execute once with the INSERT
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        params = call_args[0][1]  # positional second arg is the params dict
        assert params["design_name"] == "aes"
        assert params["symptoms"] == "hold violations"
        assert params["root_cause"] == "cts_skew"
        assert params["pdk"] == "gf180mcuD"
        assert json.loads(params["actions"]) == ["fix CTS"]
        assert json.loads(params["metrics"]) == {"wns": 0.0}

    def test_defaults_for_optional_args(self):
        ctx, mock_db = _make_ctx(return_value=1)
        with patch(_PATCH_GET_DB, return_value=ctx):
            save_case(design_name="gcd", symptoms="timing", root_cause="routing_detour")
        params = mock_db.execute.call_args[0][1]
        assert json.loads(params["actions"]) == []
        assert json.loads(params["metrics"]) == {}
        assert params["pdk"] == ""

    def test_db_exception_propagates(self):
        with patch(_PATCH_GET_DB, side_effect=Exception("DB down")):
            with pytest.raises(Exception, match="DB down"):
                save_case("gcd", "timing", "routing_detour")


# ── search_similar_cases ──────────────────────────────────────────────────────


class TestSearchSimilarCases:
    def _mock_search_db(self, fts_rows, fallback_rows=None):
        """Return a context that yields FTS rows then optionally fallback rows."""
        mock_db = MagicMock()
        calls = [fts_rows]
        if fallback_rows is not None:
            calls.append(fallback_rows)
        mock_db.execute.return_value.fetchall.side_effect = calls
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_db)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    def test_fts_results_returned(self):
        rows = _search_rows([
            {"id": 1, "symptoms": "wns bad congestion", "root_cause": "routing_detour"},
            {"id": 2, "symptoms": "hold violations", "root_cause": "cts_skew"},
        ])
        ctx = self._mock_search_db(rows)
        with patch(_PATCH_GET_DB, return_value=ctx):
            results = search_similar_cases("congestion routing")
        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[0]["root_cause"] == "routing_detour"

    def test_fallback_used_when_fts_empty(self):
        fallback_rows = _search_rows([
            {"id": 3, "symptoms": "congestion overflow", "root_cause": "density_saturation"},
        ])
        ctx = self._mock_search_db(fts_rows=[], fallback_rows=fallback_rows)
        with patch(_PATCH_GET_DB, return_value=ctx):
            results = search_similar_cases("congestion")
        assert len(results) == 1
        assert results[0]["root_cause"] == "density_saturation"

    def test_empty_results_when_both_empty(self):
        ctx = self._mock_search_db(fts_rows=[], fallback_rows=[])
        with patch(_PATCH_GET_DB, return_value=ctx):
            results = search_similar_cases("nothing matches")
        assert results == []

    def test_result_dict_has_expected_keys(self):
        rows = _search_rows([{
            "id": 10, "design_name": "gcd", "pdk": "sky130hd",
            "symptoms": "wns -0.5", "root_cause": "routing_detour",
            "actions": ["reduce util"], "result_metrics": {"wns": 0.0},
        }])
        ctx = self._mock_search_db(rows)
        with patch(_PATCH_GET_DB, return_value=ctx):
            results = search_similar_cases("wns")
        r = results[0]
        for key in ("id", "design_name", "pdk", "symptoms", "root_cause",
                    "actions", "result_metrics", "created_at"):
            assert key in r, f"Missing key: {key}"

    def test_actions_decoded_from_json_string(self):
        rows = _search_rows([{"actions": ["fix CTS", "rerun route"]}])
        ctx = self._mock_search_db(rows)
        with patch(_PATCH_GET_DB, return_value=ctx):
            results = search_similar_cases("hold")
        assert results[0]["actions"] == ["fix CTS", "rerun route"]

    def test_design_name_filter_passed_to_query(self):
        ctx = self._mock_search_db([], fallback_rows=[])
        with patch(_PATCH_GET_DB, return_value=ctx):
            search_similar_cases("timing", design_name="aes")
        # Check that design_name was included in at least one execute call's params
        mock_db = ctx.__enter__.return_value
        all_call_params = [
            str(c) for c in mock_db.execute.call_args_list
        ]
        assert any("aes" in s for s in all_call_params)

    def test_limit_respected(self):
        rows = _search_rows([{"id": i} for i in range(10)])
        ctx = self._mock_search_db(rows)
        with patch(_PATCH_GET_DB, return_value=ctx):
            results = search_similar_cases("timing", limit=3)
        # The SQL enforces LIMIT; we just verify the function passes the param
        mock_db = ctx.__enter__.return_value
        call_args_list = mock_db.execute.call_args_list
        params_used = call_args_list[0][0][1]
        assert params_used["limit"] == 3

    def test_db_exception_returns_empty_list(self):
        with patch(_PATCH_GET_DB, side_effect=Exception("DB down")):
            results = search_similar_cases("timing")
        assert results == []

    def test_returns_list_not_none(self):
        with patch(_PATCH_GET_DB, side_effect=Exception("DB down")):
            results = search_similar_cases("anything")
        assert isinstance(results, list)


# ── result_metrics deserialization ───────────────────────────────────────────


def test_metrics_decoded_when_already_dict():
    """If the DB driver returns a dict (e.g. via JSON type), no double-decode."""
    rows = [(1, "gcd", "sky130hd", "wns bad", "routing_detour",
             ["fix"], {"wns": 0.0}, "2026-01-01")]
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchall.return_value = rows
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch(_PATCH_GET_DB, return_value=ctx):
        results = search_similar_cases("wns")
    assert results[0]["result_metrics"] == {"wns": 0.0}
    assert results[0]["actions"] == ["fix"]
