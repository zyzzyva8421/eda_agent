"""Tests for the backend abstraction layer."""

from __future__ import annotations

import pytest

from eda_agent.backends import get_backend, list_backends, register_backend
from eda_agent.backends.base import (
    AbstractEDABackend,
    DesignSpec,
    ReportFile,
    RunResult,
    StageStatus,
)
from eda_agent.backends.orfs import ORFSBackend


def test_list_backends():
    backends = list_backends()
    assert "orfs" in backends
    assert "innovus" in backends
    assert "icc2" in backends


def test_get_backend_orfs():
    b = get_backend("orfs")
    assert b.name == "orfs"
    assert "synth" in b.get_supported_stages()
    assert "route" in b.get_supported_stages()


def test_get_backend_unknown():
    with pytest.raises(KeyError, match="Unknown backend"):
        get_backend("nonexistent_tool")


def test_validate_params_bad_stage():
    b = get_backend("orfs")
    with pytest.raises(ValueError, match="not supported"):
        b.validate_params("invalid_stage", {})


def test_innovus_stub_not_available():
    b = get_backend("innovus")
    assert not b.is_available()


def test_icc2_stub_not_available():
    b = get_backend("icc2")
    assert not b.is_available()


def test_register_custom_backend():
    class CustomBackend(AbstractEDABackend):
        @property
        def name(self):
            return "custom_pr"

        @property
        def version(self):
            return "1.0"

        def get_supported_stages(self):
            return ["route", "signoff"]

        def run_stage(self, stage, design, params):
            raise NotImplementedError

        def collect_reports(self, result):
            return []

    cb = CustomBackend()
    register_backend(cb)
    assert get_backend("custom_pr").name == "custom_pr"
    assert "custom_pr" in list_backends()


def test_orfs_is_available_without_install(tmp_path):
    """ORFSBackend.is_available() returns False when the path doesn't exist."""
    b = ORFSBackend(orfs_root=tmp_path / "nonexistent")
    assert not b.is_available()
