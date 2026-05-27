"""Tests for the shared session_store module (CLI + API persistence)."""

from __future__ import annotations

from unittest.mock import MagicMock

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
# default_cli_session_id
# ---------------------------------------------------------------------------


def test_default_cli_session_id_uses_username(monkeypatch):
    monkeypatch.setenv("USER", "alice")
    assert session_store.default_cli_session_id() == "cli-alice-default"
