"""Tests for migration compatibility helpers."""

from __future__ import annotations

from importlib import import_module
from unittest.mock import MagicMock, Mock, patch

initial_schema = import_module("eda_agent.db.migrations.versions.0001_initial_schema")
env_snapshot = import_module("eda_agent.db.migrations.versions.0010_add_flow_session_env_snapshot")
reason_structured = import_module(
    "eda_agent.db.migrations.versions.0011_add_decision_trace_structured_reason"
)


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


def test_supports_postgresql_jsonb_false_on_postgresql_92():
    mock_bind = Mock()
    mock_bind.dialect.server_version_info = (9, 2, 24)

    assert env_snapshot._supports_postgresql_jsonb(mock_bind) is False


def test_supports_postgresql_jsonb_true_on_postgresql_94():
    mock_bind = Mock()
    mock_bind.dialect.server_version_info = (9, 4, 0)

    assert env_snapshot._supports_postgresql_jsonb(mock_bind) is True


def test_supports_postgresql_jsonb_uses_server_version_num_fallback():
    mock_bind = MagicMock()
    mock_bind.dialect.server_version_info = None
    mock_bind.execute.return_value.scalar.return_value = "90224"

    assert env_snapshot._supports_postgresql_jsonb(mock_bind) is False


def test_upgrade_skips_env_snapshot_gin_index_on_postgresql_without_jsonb():
    mock_bind = Mock()
    mock_bind.dialect.name = "postgresql"
    mock_bind.dialect.server_version_info = (9, 2, 24)

    with patch.object(env_snapshot, "op") as mock_op:
        mock_op.get_bind.return_value = mock_bind

        env_snapshot.upgrade()

    mock_op.create_index.assert_not_called()


def test_upgrade_creates_env_snapshot_gin_index_on_postgresql_with_jsonb():
    mock_bind = Mock()
    mock_bind.dialect.name = "postgresql"
    mock_bind.dialect.server_version_info = (9, 4, 0)

    with patch.object(env_snapshot, "op") as mock_op:
        mock_op.get_bind.return_value = mock_bind

        env_snapshot.upgrade()

    mock_op.create_index.assert_called_once_with(
        "ix_flow_sessions_env_snapshot_gin",
        "flow_sessions",
        ["env_snapshot"],
        postgresql_using="gin",
    )


def test_supports_postgresql_to_json_false_on_postgresql_92():
    mock_bind = Mock()
    mock_bind.dialect.server_version_info = (9, 2, 24)

    assert reason_structured._supports_postgresql_to_json(mock_bind) is False


def test_supports_postgresql_to_json_true_on_postgresql_93():
    mock_bind = Mock()
    mock_bind.dialect.server_version_info = (9, 3, 0)

    assert reason_structured._supports_postgresql_to_json(mock_bind) is True


def test_upgrade_uses_replace_fallback_without_to_json():
    mock_bind = Mock()
    mock_bind.dialect.name = "postgresql"
    mock_bind.dialect.server_version_info = (9, 2, 24)

    with patch.object(reason_structured, "op") as mock_op:
        mock_op.get_bind.return_value = mock_bind

        reason_structured.upgrade()

    sql_calls = [str(call.args[0]).lower() for call in mock_op.execute.call_args_list]
    assert any("replace(" in sql for sql in sql_calls)
    assert not any("to_json(" in sql for sql in sql_calls)
