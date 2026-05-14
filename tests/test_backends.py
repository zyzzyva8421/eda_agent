"""Tests for the backend abstraction layer."""

from __future__ import annotations

import subprocess

import pytest

from eda_agent.backends import get_backend, list_backends, register_backend
from eda_agent.backends.base import AbstractEDABackend
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


def test_innovus_available():
    """InnovusBackend.is_available() returns True when SSH is configured."""
    b = get_backend("innovus")
    # Note: This test passes when VM is running and SSH is accessible
    assert b.is_available()


def test_innovus_supports_intermediate_physical_stages():
    from eda_agent.backends.innovus import _INNOVUS_REPORT_PATTERNS

    b = get_backend("innovus")
    stages = b.get_supported_stages()

    for stage in ("place", "prects", "cts", "postcts", "route", "postroute", "signoff"):
        assert stage in stages
        report_types = {report_type for _, report_type in _INNOVUS_REPORT_PATTERNS[stage]}
        assert "innovus_congestion" in report_types
        assert "innovus_congestion_map" in report_types


def test_innovus_transient_ssh_failure_detection():
    b = get_backend("innovus")
    result = subprocess.CompletedProcess(
        args=["ssh"],
        returncode=255,
        stdout="",
        stderr="ssh: connect to host 192.168.58.10 port 22: No route to host",
    )
    assert b._is_transient_ssh_failure(result)


def test_innovus_non_transient_ssh_failure_detection():
    b = get_backend("innovus")
    result = subprocess.CompletedProcess(
        args=["ssh"],
        returncode=255,
        stdout="",
        stderr="Permission denied (publickey,password)",
    )
    assert not b._is_transient_ssh_failure(result)


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
