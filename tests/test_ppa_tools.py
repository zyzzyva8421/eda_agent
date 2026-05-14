"""Tests for the PPA target checker and multistage tuning helpers.

These tests exercise pure logic (no DB/LLM/EDA tool required).
"""

from __future__ import annotations

# ── _check_ppa_target ─────────────────────────────────────────────────────────


def _make_timing(
    wns=None,
    tns=None,
    fep=None,
    fmax=None,
    setup_violations=None,
    hold_violations=None,
):
    """Build a minimal timing dict compatible with _check_ppa_target."""
    return {
        "summary": [
            {
                "wns_ns": wns,
                "tns_ns": tns,
                "failing_endpoints": fep,
                "fmax_mhz": fmax,
                "setup_violations": setup_violations,
                "hold_violations": hold_violations,
            }
        ]
    }


def test_check_ppa_target_wns_met():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(wns=-0.05), "WNS >= -0.1") is True


def test_check_ppa_target_wns_not_met():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(wns=-0.5), "WNS >= -0.1") is False


def test_check_ppa_target_tns():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(wns=0.1, tns=0.0, fep=0), "TNS >= -1.0") is True
    assert _check_ppa_target(_make_timing(wns=0.1, tns=-5.0, fep=0), "TNS >= -1.0") is False


def test_check_ppa_target_fmax():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(fmax=500.0), "fmax >= 400") is True
    assert _check_ppa_target(_make_timing(fmax=300.0), "fmax >= 400") is False


def test_check_ppa_target_fep():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(fep=0), "fep == 0") is True
    assert _check_ppa_target(_make_timing(fep=3), "fep == 0") is False


def test_check_ppa_target_hold_violations():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(hold_violations=0), "hold_violations == 0") is True
    assert _check_ppa_target(_make_timing(hold_violations=2), "hold_violations == 0") is False


def test_check_ppa_target_multi_condition():
    """Multiple conditions joined by 'and' must all be satisfied."""
    from eda_agent.agent.tools import _check_ppa_target

    t = _make_timing(wns=-0.05, fep=0)
    assert _check_ppa_target(t, "WNS >= -0.1 and fep == 0") is True

    t_fail = _make_timing(wns=-0.05, fep=3)
    assert _check_ppa_target(t_fail, "WNS >= -0.1 and fep == 0") is False


def test_check_ppa_target_empty_summary():
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target({"summary": []}, "WNS >= -0.1") is False


def test_check_ppa_target_fallback_fep_zero():
    """Unparseable spec → fall back to FEP == 0."""
    from eda_agent.agent.tools import _check_ppa_target

    assert _check_ppa_target(_make_timing(fep=0), "all timing clean") is True
    assert _check_ppa_target(_make_timing(fep=1), "all timing clean") is False


def test_check_ppa_target_missing_metric():
    """Condition on a metric that is None → not satisfied."""
    from eda_agent.agent.tools import _check_ppa_target

    # fmax is None in the summary → condition cannot be verified → False
    assert _check_ppa_target(_make_timing(fmax=None), "fmax >= 400") is False


def test_check_ppa_target_overflow_condition():
    from eda_agent.agent.tools import _check_ppa_target

    t = _make_timing(fep=0)
    assert _check_ppa_target(
        t,
        "overflow_h_pct <= 2.0",
        congestion_summary={"overflow_h_pct": 1.8, "overflow_v_pct": 1.0},
    ) is True
    assert _check_ppa_target(
        t,
        "overflow_h_pct <= 2.0",
        congestion_summary={"overflow_h_pct": 2.2, "overflow_v_pct": 1.0},
    ) is False


# ── Param filtering (regression for P0.1 fix) ────────────────────────────────


def test_filter_suggested_params_orfs_keeps_only_numeric_values():
    """ORFS 仍应丢弃 advisory/non-numeric 字符串。"""
    from eda_agent.agent.tools import _filter_suggested_params

    raw_params = {
        "CLOCK_PERIOD": "increase by 0.5 ns",  # advisory – must be dropped
        "CORE_UTILIZATION": 45,                  # integer – must be kept
        "TNS_END_PERCENT": "20",                 # numeric string – must be kept
        "SOME_FLAG": "enable",                   # non-numeric string – must be dropped
    }

    filtered = _filter_suggested_params(raw_params, backend="orfs", stage="place")

    assert "CLOCK_PERIOD" not in filtered, "Advisory string should be dropped"
    assert "SOME_FLAG" not in filtered, "Non-numeric string should be dropped"
    assert filtered["CORE_UTILIZATION"] == 45
    assert filtered["TNS_END_PERCENT"] == "20"


def test_filter_suggested_params_innovus_accepts_enum_and_boolean():
    """Innovus 应允许阶段目录中的枚举/布尔参数。"""
    from eda_agent.agent.tools import _filter_suggested_params

    raw_params = {
        "place_cong_effort": "high",
        "place_global_SPP_enhancement": "true",
        "unknown_param": "foo",
        "route_ppa_2": True,
    }

    filtered = _filter_suggested_params(raw_params, backend="innovus", stage="place")

    assert filtered["place_cong_effort"] == "high"
    assert filtered["place_global_SPP_enhancement"] is True
    assert "unknown_param" not in filtered
    assert "route_ppa_2" not in filtered, "route-only param should be dropped for place stage"


# ── _pick_bottleneck_stage ────────────────────────────────────────────────────


def test_pick_bottleneck_hold_violations():
    from eda_agent.agent.tools import _pick_bottleneck_stage

    timing = _make_timing(wns=-0.1, fep=2, hold_violations=3)
    assert _pick_bottleneck_stage(timing) == "cts"


def test_pick_bottleneck_severe_setup():
    from eda_agent.agent.tools import _pick_bottleneck_stage

    timing = _make_timing(wns=-0.8, fep=25, setup_violations=15)
    assert _pick_bottleneck_stage(timing) == "cts"


def test_pick_bottleneck_mild_setup_route():
    from eda_agent.agent.tools import _pick_bottleneck_stage

    timing = _make_timing(wns=-0.1, fep=5)
    assert _pick_bottleneck_stage(timing) == "route"


def test_pick_bottleneck_clean():
    from eda_agent.agent.tools import _pick_bottleneck_stage

    timing = _make_timing(wns=0.1, fep=0)
    assert _pick_bottleneck_stage(timing) == "place"


def test_pick_bottleneck_congestion_forces_place():
    from unittest.mock import patch

    from eda_agent.agent.tools import _pick_bottleneck_stage

    timing = _make_timing(wns=-0.2, fep=5)
    with patch(
        "eda_agent.agent.tools._query_congestion_summary",
        return_value={"overflow_h_pct": 3.2, "overflow_v_pct": 1.5},
    ):
        assert _pick_bottleneck_stage(timing, run_id=123) == "place"


# ── Tool schema coverage ──────────────────────────────────────────────────────


def test_tune_ppa_multistage_schema_registered():
    """tune_ppa_multistage must appear in TOOL_SCHEMAS and the dispatch table."""
    from eda_agent.agent.tools import _TOOL_DISPATCH, TOOL_SCHEMAS

    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert "tune_ppa_multistage" in names, "tune_ppa_multistage must be in TOOL_SCHEMAS"
    assert "tune_congestion_with_blockage" in names
    assert "add_placement_blockage" in names
    assert "query_congestion_summary" in names
    assert "tune_ppa_multistage" in _TOOL_DISPATCH, "tune_ppa_multistage must be dispatchable"
    assert "tune_congestion_with_blockage" in _TOOL_DISPATCH
    assert "add_placement_blockage" in _TOOL_DISPATCH
    assert "query_congestion_summary" in _TOOL_DISPATCH


def test_tune_ppa_multistage_schema_required_params():
    from eda_agent.agent.tools import TOOL_SCHEMAS

    schema = next(
        s for s in TOOL_SCHEMAS if s["function"]["name"] == "tune_ppa_multistage"
    )
    required = schema["function"]["parameters"]["required"]
    for field in ("backend", "design_name", "design_config", "pdk", "target_spec"):
        assert field in required


def test_all_tool_schemas_have_description():
    """Every tool schema must have a non-empty description."""
    from eda_agent.agent.tools import TOOL_SCHEMAS

    for s in TOOL_SCHEMAS:
        name = s["function"]["name"]
        desc = s["function"].get("description", "")
        assert desc, f"Tool '{name}' is missing a description"


# ── Extended timing fields propagate through ingest logic ────────────────────


def test_ingest_extended_timing_fields_included_in_insert():
    """_ingest_records must attempt to write extended timing fields.

    We verify the INSERT SQL contains the new column names by inspecting
    the mock DB call – no real DB is needed.
    """
    from unittest.mock import MagicMock, patch

    mock_db = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_db)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    rec = {
        "kind": "summary",
        "view": "setup_typical",
        "wns_ns": -0.342,
        "tns_ns": -12.451,
        "failing_endpoints": 7,
        "fmax_mhz": 238.86,
        "clock_skew_ns": 0.12,
        "max_slew_violations": 3,
        "max_fanout_violations": 1,
        "max_cap_violations": 0,
        "setup_violations": 7,
        "hold_violations": 2,
        "critical_path_delay_ns": 4.19,
        "slack_cpd_ratio_pct": 0.918,
    }

    with patch("eda_agent.agent.tools.get_db", return_value=mock_ctx):
        from eda_agent.agent.tools import _ingest_records
        _ingest_records([rec], run_id=1, stage="route")

    # Verify the INSERT statement contained extended field names
    assert mock_db.execute.called
    call_args = mock_db.execute.call_args_list[0]
    sql_text = str(call_args[0][0])
    for col in (
        "fmax_mhz",
        "clock_skew_ns",
        "max_slew_violations",
        "max_fanout_violations",
        "max_cap_violations",
        "setup_violations",
        "hold_violations",
        "critical_path_delay_ns",
        "slack_cpd_ratio_pct",
    ):
        assert col in sql_text, f"Extended column '{col}' missing from INSERT"
