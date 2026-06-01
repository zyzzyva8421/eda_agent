"""Tests for the shared session_store module (CLI + API persistence)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from psycopg2.extras import Json

from eda_agent.agent import session_store
from eda_agent.agent.memory import AgentMemory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(row):
    """Build a MagicMock SQLAlchemy session that returns ``row`` from a SELECT."""
    db = MagicMock()
    result = MagicMock()
    mapping = MagicMock()
    mapping.first.return_value = row
    result.mappings.return_value = mapping
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# load_session
# ---------------------------------------------------------------------------


def test_load_session_returns_empty_when_row_missing():
    db = _make_db(None)
    mem = session_store.load_session("nonexistent", db)
    assert isinstance(mem, AgentMemory)
    assert len(mem) == 0


def test_load_session_restores_history_and_scratchpad():
    row = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        "scratchpad": {"context": {"design_name": "aes"}},
    }
    db = _make_db(row)
    mem = session_store.load_session("s1", db)
    assert len(mem) == 2
    assert mem.context()["design_name"] == "aes"


def test_load_session_handles_db_none():
    mem = session_store.load_session("anything", None)
    assert isinstance(mem, AgentMemory)
    assert len(mem) == 0


def test_load_session_handles_legacy_row_without_scratchpad():
    row = {
        "messages": [{"role": "user", "content": "hi"}],
        # Old rows have no `scratchpad` column.
    }
    db = _make_db(row)
    mem = session_store.load_session("legacy", db)
    assert len(mem) == 1
    assert mem.context() == {}


# ---------------------------------------------------------------------------
# save_session
# ---------------------------------------------------------------------------


def test_save_session_writes_to_db():
    db = MagicMock()
    mem = AgentMemory()
    mem.add_user("hi")
    mem.set("design_name", "aes")
    session_store.save_session("s1", "alice", mem, db)
    assert db.execute.called
    assert db.commit.called


def test_save_session_passes_native_json_objects_to_db():
    db = MagicMock()
    mem = AgentMemory()
    mem.add_user("hi")
    mem.add_assistant("hello")
    mem.set("design_name", "aes")

    session_store.save_session("s1", "alice", mem, db)

    _sql, params = db.execute.call_args.args
    assert isinstance(params["msgs"], Json)
    assert isinstance(params["scratch"], Json)


def test_save_session_falls_back_without_on_conflict_support():
    db = MagicMock()
    update_result = MagicMock()
    update_result.rowcount = 0
    db.execute.side_effect = [update_result, None]
    mem = AgentMemory()
    mem.add_user("hi")
    mem.set("design_name", "aes")

    with patch("eda_agent.agent.session_store.supports_postgresql_on_conflict", return_value=False):
        session_store.save_session("s1", "alice", mem, db)

    assert db.execute.call_count == 2
    first_sql = str(db.execute.call_args_list[0].args[0])
    second_sql = str(db.execute.call_args_list[1].args[0])
    assert "UPDATE agent_sessions" in first_sql
    assert "INSERT INTO agent_sessions" in second_sql
    assert db.commit.called


def test_load_session_falls_back_when_scratchpad_column_missing():
    db = MagicMock()

    class MissingScratchpad(Exception):
        pass

    first_exc = MissingScratchpad('column "scratchpad" does not exist')
    fallback_result = MagicMock()
    fallback_mapping = MagicMock()
    fallback_mapping.first.return_value = {
        "messages": [{"role": "user", "content": "hi"}],
    }
    fallback_result.mappings.return_value = fallback_mapping

    db.execute.side_effect = [first_exc, fallback_result]

    mem = session_store.load_session("legacy", db)
    assert len(mem) == 1
    assert mem.get_messages()[0]["content"] == "hi"
    assert mem.context() == {}
    assert db.rollback.called


def test_save_session_falls_back_when_scratchpad_column_missing():
    db = MagicMock()

    class MissingScratchpad(Exception):
        pass

    first_exc = MissingScratchpad('column "scratchpad" does not exist')
    db.execute.side_effect = [first_exc, None]

    mem = AgentMemory()
    mem.add_user("hi")

    with patch("eda_agent.agent.session_store.supports_postgresql_on_conflict", return_value=True):
        session_store.save_session("legacy", "alice", mem, db)
    assert db.execute.call_count == 2
    assert db.rollback.called
    assert db.commit.called


def test_save_session_legacy_fallback_without_on_conflict_support():
    db = MagicMock()

    class MissingScratchpad(Exception):
        pass

    first_exc = MissingScratchpad('column "scratchpad" does not exist')
    update_result = MagicMock()
    update_result.rowcount = 0
    db.execute.side_effect = [first_exc, update_result, None]

    mem = AgentMemory()
    mem.add_user("hi")

    with patch("eda_agent.agent.session_store.supports_postgresql_on_conflict", return_value=False):
        session_store.save_session("legacy", "alice", mem, db)

    assert db.execute.call_count == 3
    assert "UPDATE agent_sessions" in str(db.execute.call_args_list[1].args[0])
    assert "INSERT INTO agent_sessions" in str(db.execute.call_args_list[2].args[0])
    assert db.rollback.called
    assert db.commit.called


def test_save_session_noop_when_db_none():
    mem = AgentMemory()
    mem.add_user("x")
    # Just checking nothing raises.
    session_store.save_session("s1", "alice", mem, None)


def test_save_session_enforces_byte_budget():
    db = MagicMock()
    mem = AgentMemory()
    for _ in range(50):
        mem.add_user("x" * 50_000)
    session_store.save_session("big", "alice", mem, db)
    # Memory must have been shrunk in place to fit MAX_SESSION_BYTES.
    import json

    payload = json.dumps([AgentMemory._serialise(m) for m in mem._history])
    assert len(payload.encode()) <= session_store.MAX_SESSION_BYTES


# ---------------------------------------------------------------------------
# clear_session
# ---------------------------------------------------------------------------


def test_clear_session_deletes_row():
    db = MagicMock()
    session_store.clear_session("s1", db)
    assert db.execute.called
    assert db.commit.called


def test_clear_session_noop_when_db_none():
    session_store.clear_session("s1", None)  # Must not raise.


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_counts_messages_from_python_list():
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = [
        ("s1", "alice", "2026-01-01T00:00:00Z", [{"role": "user"}, {"role": "assistant"}]),
    ]
    db.execute.return_value = result

    rows = session_store.list_sessions("alice", db, limit=20)

    assert len(rows) == 1
    assert rows[0].session_id == "s1"
    assert rows[0].username == "alice"
    assert rows[0].message_count == 2


def test_list_sessions_counts_messages_from_json_string():
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = [
        ("s2", "alice", "2026-01-01T00:00:00Z", '[{"role":"user"},{"role":"assistant"}]'),
    ]
    db.execute.return_value = result

    rows = session_store.list_sessions("alice", db, limit=20)

    assert len(rows) == 1
    assert rows[0].session_id == "s2"
    assert rows[0].message_count == 2


# ---------------------------------------------------------------------------
# default_cli_session_id
# ---------------------------------------------------------------------------


def test_default_cli_session_id_uses_username(monkeypatch):
    monkeypatch.setenv("USER", "alice")
    assert session_store.default_cli_session_id() == "cli-alice-default"
