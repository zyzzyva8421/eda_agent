"""Tests for the iterative optimisation loop (eda_agent.agent.optimization_loop).

Relies on the same mock-DB fixtures as ``test_inference_engine.py``:
- ``infer`` and ``confirm`` are tested separately; we mock them here.
- ``_run_eda_stage``, ``_query_timing``, etc. are mocked so no real backend or
  DB is needed.
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

import pytest

from eda_agent.agent.optimization_loop import (
    IterationRecord,
    OptimizationLoop,
    optimize_with_inference,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def mock_infer():
    """Patch eda_agent.agent.inference.engine.infer."""
    with patch("eda_agent.agent.optimization_loop.infer") as m:
        yield m


@pytest.fixture
def mock_confirm():
    """Patch eda_agent.agent.inference.engine.confirm."""
    with patch("eda_agent.agent.optimization_loop.confirm") as m:
        yield m


@pytest.fixture
def mock_run_stage():
    """Patch _run_eda_stage to return a synthetic success result."""
    with patch(
        "eda_agent.agent.optimization_loop.OptimizationLoop._execute_stage"
    ) as m:
        m.return_value = {
            "run_id": 201,
            "status": "success",
            "stage": "place",
            "backend": "innovus",
        }
        yield m


@pytest.fixture(autouse=True)
def mock_check_target():
    """Default: target NOT met (loop continues)."""
    with patch(
        "eda_agent.agent.optimization_loop.OptimizationLoop._check_target"
    ) as m:
        m.return_value = False
        yield m


# ── IterationRecord ──────────────────────────────────────────────────────


def test_iteration_record_to_dict():
    rec = IterationRecord(
        iteration=1,
        inference_id=42,
        cause_id="routing_detour",
        cause_display_name="Routing Detour",
        experiment_action="increase_cong_effort",
        experiment_risk="low",
        params_applied={"place_cong_effort": "high"},
        new_run_id=101,
        new_run_status="success",
        converged=False,
        target_met=False,
        score_dropped=False,
    )
    d = rec.to_dict()
    assert d["iteration"] == 1
    assert d["cause_id"] == "routing_detour"
    assert d["params_applied"] == {"place_cong_effort": "high"}


# ── _select_experiment ───────────────────────────────────────────────────


def test_select_experiment_empty_hypotheses():
    assert OptimizationLoop._select_experiment([]) is None


def test_select_experiment_no_experiments():
    h = [{"cause_id": "x", "display_name": "X", "experiments": []}]
    assert OptimizationLoop._select_experiment(h) is None


def test_select_experiment_prefers_low_risk():
    h = [
        {
            "cause_id": "timing_detour",
            "display_name": "Timing Detour",
            "experiments": [
                {"action": "high_risk_action", "risk": "high", "param_hint": {}},
                {"action": "safe_action", "risk": "low", "param_hint": {}},
            ],
        }
    ]
    exp = OptimizationLoop._select_experiment(h)
    assert exp is not None
    assert exp["action"] == "safe_action"
    assert exp["risk"] == "low"


def test_select_experiment_falls_back_to_any_risk():
    h = [
        {
            "cause_id": "routing",
            "display_name": "Routing",
            "experiments": [
                {"action": "only_option", "risk": "medium", "param_hint": {}}
            ],
        }
    ]
    exp = OptimizationLoop._select_experiment(h)
    assert exp is not None
    assert exp["action"] == "only_option"


# ── _experiment_to_params ────────────────────────────────────────────────


def test_experiment_to_params_empty_hint():
    assert OptimizationLoop._experiment_to_params({"param_hint": {}}) == {}


def test_experiment_to_params_string_to_numeric():
    exp = {
        "param_hint": {
            "CORE_UTILIZATION": "0.85",
            "place_cong_effort": "high",
            "max_iter": "5",
        }
    }
    params = OptimizationLoop._experiment_to_params(exp)
    assert params["CORE_UTILIZATION"] == 0.85  # float
    assert params["place_cong_effort"] == "high"  # kept as string
    assert params["max_iter"] == 5  # int


# ── _score_dropped_below_threshold ───────────────────────────────────────


def test_score_dropped_empty_hypotheses():
    assert OptimizationLoop._score_dropped_below_threshold([], 0.35) is True


def test_score_above_threshold_not_dropped():
    h = [{"cause_id": "x", "score": 0.7}]
    assert OptimizationLoop._score_dropped_below_threshold(h, 0.35) is False


def test_score_below_threshold():
    h = [{"cause_id": "x", "score": 0.2}]
    assert OptimizationLoop._score_dropped_below_threshold(h, 0.35) is True


# ── orchestrate (integration-level with mocks) ───────────────────────────


def test_orchestrate_converges_via_target(
    mock_infer, mock_confirm, mock_check_target, mock_run_stage
):
    """Loop stops when target is met."""
    mock_infer.return_value = {
        "inference_id": 42,
        "run_id": 100,
        "hypotheses": [
            {
                "cause_id": "routing_detour",
                "display_name": "Routing Detour",
                "score": 1.0,
                "experiments": [
                    {
                        "action": "increase_cong_effort",
                        "risk": "low",
                        "param_hint": {"place_cong_effort": "high"},
                    }
                ],
            }
        ],
    }
    # First check returns False, second returns True (converged)
    mock_check_target.side_effect = [False, True]

    loop = OptimizationLoop(session_id=1, max_iterations=5)
    result = loop.orchestrate(
        run_id=100,
        target_spec="WNS >= -0.1",
        backend="innovus",
        stage="place",
        design_name="aes",
        design_config="/cfg/aes.mk",
        pdk="sky130hd",
    )

    assert result["converged"] is True
    assert result["iterations_run"] == 2
    assert len(loop.history) == 2
    # Phase B confirm was called
    mock_confirm.assert_called_once_with(42, "routing_detour")


def test_orchestrate_converges_via_score_drop(
    mock_infer, mock_confirm, mock_check_target, mock_run_stage
):
    """Loop stops when the inference engine score drops below threshold."""
    # First infer: high score
    # Second infer (verify): low score → convergence
    mock_infer.side_effect = [
        {
            "inference_id": 42,
            "run_id": 100,
            "hypotheses": [
                {
                    "cause_id": "routing_detour",
                    "display_name": "Routing Detour",
                    "experiments": [
                        {
                            "action": "increase_cong_effort",
                            "risk": "low",
                            "param_hint": {},
                        }
                    ],
                }
            ],
        },
        {
            "inference_id": 43,
            "run_id": 201,
            "hypotheses": [
                {"cause_id": "routing_detour", "score": 0.15}  # below 0.35
            ],
        },
    ]

    loop = OptimizationLoop(session_id=1, max_iterations=5)
    result = loop.orchestrate(
        run_id=100,
        target_spec="WNS >= -0.1",
        backend="orfs",
        stage="route",
        design_name="aes",
        design_config="/cfg/aes.mk",
        pdk="sky130hd",
    )

    assert result["converged"] is True
    assert result["iterations_run"] == 1
    # Phase B confirm was called
    mock_confirm.assert_called_once_with(42, "routing_detour")


def test_orchestrate_no_experiment_stops_early(
    mock_infer, mock_confirm
):
    """Loop exits when the inference yields no actionable experiment."""
    mock_infer.return_value = {
        "inference_id": 99,
        "run_id": 100,
        "hypotheses": [
            {
                "cause_id": "unknown",
                "display_name": "Unknown",
                "experiments": [],
            }
        ],
    }

    loop = OptimizationLoop(session_id=1, max_iterations=5)
    result = loop.orchestrate(
        run_id=100,
        target_spec="WNS >= 0",
        backend="innovus",
        stage="place",
        design_name="gcd",
        design_config="/cfg/gcd.mk",
        pdk="tsmc18",
    )

    assert result["converged"] is False
    assert result["iterations_run"] == 1
    mock_confirm.assert_not_called()


def test_orchestrate_max_iterations(
    mock_infer, mock_confirm, mock_check_target, mock_run_stage
):
    """Loop stops at max_iterations without convergence."""
    mock_infer.return_value = {
        "inference_id": -1,
        "run_id": 100,
        "hypotheses": [
            {
                "cause_id": "routing_detour",
                "display_name": "Routing Detour",
                "score": 1.0,
                "experiments": [
                    {
                        "action": "try_something",
                        "risk": "low",
                        "param_hint": {},
                    }
                ],
            }
        ],
    }
    # Target never met → loop exhausts iterations
    mock_check_target.return_value = False

    loop = OptimizationLoop(session_id=1, max_iterations=3)
    result = loop.orchestrate(
        run_id=100,
        target_spec="WNS >= 0",
        backend="innovus",
        stage="place",
        design_name="gcd",
        design_config="/cfg/gcd.mk",
        pdk="tsmc18",
    )

    assert result["converged"] is False
    assert result["iterations_run"] == 3
    mock_confirm.assert_not_called()


# ── optimize_with_inference (convenience wrapper) ────────────────────────


@patch("eda_agent.agent.optimization_loop.OptimizationLoop")
@patch("eda_agent.agent.tools._create_flow_session")
def test_optimize_with_inference_creates_session(
    mock_create_session, mock_loop_cls
):
    """Wrapper creates a flow session when session_id is omitted."""
    mock_create_session.return_value = 77
    mock_loop_instance = MagicMock()
    mock_loop_instance.orchestrate.return_value = {"converged": True}
    mock_loop_cls.return_value = mock_loop_instance

    result = optimize_with_inference(
        run_id=100,
        target_spec="WNS >= 0",
        backend="innovus",
        stage="place",
        design_name="aes",
        design_config="/cfg/aes.mk",
        pdk="sky130hd",
        max_iterations=3,
    )

    assert result["session_id"] == 77
    mock_create_session.assert_called_once()
    mock_loop_instance.orchestrate.assert_called_once()
