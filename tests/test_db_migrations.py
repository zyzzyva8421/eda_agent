"""Tests for migration compatibility helpers."""

from __future__ import annotations

from importlib import import_module
from unittest.mock import MagicMock, Mock


initial_schema = import_module("eda_agent.db.migrations.versions.0001_initial_schema")


def test_supports_postgresql_on_conflict_false_on_postgresql_94():
    mock_bind = Mock()
    mock_bind.dialect.server_version_info = (9, 4, 26)

    assert initial_schema._supports_postgresql_on_conflict(mock_bind) is False


def test_supports_postgresql_on_conflict_true_on_postgresql_95():
    mock_bind = Mock()
    mock_bind.dialect.server_version_info = (9, 5, 0)

    assert initial_schema._supports_postgresql_on_conflict(mock_bind) is True


def test_supports_postgresql_on_conflict_uses_server_version_num_fallback():
    mock_bind = MagicMock()
    mock_bind.dialect.server_version_info = None
    mock_bind.execute.return_value.scalar.return_value = "90426"

    assert initial_schema._supports_postgresql_on_conflict(mock_bind) is False
