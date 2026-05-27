"""Tests for AgentMemory.to_dict / from_dict + pair-aware eviction.

These exercise the L1+L2 short-term memory layer without touching the
database; persistence integration is covered separately in
``test_session_store.py``.
"""

from __future__ import annotations

import json

from eda_agent.agent.memory import AgentMemory, Message


# ---------------------------------------------------------------------------
# Round-trip persistence
# ---------------------------------------------------------------------------


def test_to_dict_round_trip_preserves_history_and_context():
    mem = AgentMemory()
    mem.add_user("run aes")
    mem.add_assistant("ok", tool_calls=[
        {"id": "c1", "type": "function",
         "function": {"name": "run_eda_stage", "arguments": "{}"}}
    ])
    mem.add_tool_result("run_eda_stage", '{"design_name": "aes", "pdk": "sky130hd"}',
                         tool_call_id="c1")
    mem.set("design_name", "aes")
    mem.set("pdk", "sky130hd")

    payload = mem.to_dict()
    assert payload["scratchpad"]["context"]["design_name"] == "aes"
    assert payload["scratchpad"]["context"]["pdk"] == "sky130hd"
    # Must round-trip cleanly via JSON since that's how we ship to the DB.
    payload = json.loads(json.dumps(payload))

    mem2 = AgentMemory.from_dict(payload)
    assert mem2.context()["design_name"] == "aes"
    msgs = mem2.get_messages()
    assert msgs[1]["tool_calls"][0]["id"] == "c1"
    assert msgs[2]["tool_call_id"] == "c1"


def test_internal_keys_not_persisted_by_default():
    mem = AgentMemory()
    mem.set("design_name", "aes")
    mem.set("_similar_cases", [{"id": 1}])

    payload = mem.to_dict()
    assert "context" in payload["scratchpad"]
    assert payload["scratchpad"]["context"] == {"design_name": "aes"}
    # The _internal namespace must not leak into the persisted dict.
    assert "_internal" not in payload["scratchpad"]


def test_persist_internal_opt_in():
    mem = AgentMemory()
    mem.set("_x", 1)
    payload = mem.to_dict(persist_internal=True)
    assert payload["scratchpad"]["_internal"] == {"_x": 1}


# ---------------------------------------------------------------------------
# Pair-aware eviction
# ---------------------------------------------------------------------------


def test_eviction_does_not_leave_orphan_tool_messages():
    mem = AgentMemory(max_messages=3)
    mem.add_user("u1")
    mem.add_assistant("", tool_calls=[
        {"id": "c1", "type": "function",
         "function": {"name": "tool", "arguments": "{}"}}
    ])
    mem.add_tool_result("tool", "result-1", tool_call_id="c1")
    # Adding 3 more should evict the first user msg AND the assistant/tool pair.
    mem.add_user("u2")
    mem.add_assistant("hi")
    msgs = mem.get_messages()

    # No orphan tool messages should remain at the front.
    assert all(
        not (i == 0 and m["role"] == "tool") for i, m in enumerate(msgs)
    )
    # And every tool message that *is* present must have its matching assistant
    # turn earlier in the list.
    for i, m in enumerate(msgs):
        if m["role"] == "tool":
            preceding_roles = [pm["role"] for pm in msgs[:i]]
            assert "assistant" in preceding_roles


def test_max_messages_bounded_basic():
    # Same behaviour as before for user-only sequences.
    mem = AgentMemory(max_messages=3)
    for i in range(5):
        mem.add_user(f"msg {i}")
    assert len(mem) == 3


# ---------------------------------------------------------------------------
# Orphan sanitisation in from_dict
# ---------------------------------------------------------------------------


def test_from_dict_drops_orphan_tool_messages():
    payload = {
        "messages": [
            {"role": "user", "content": "x"},
            # Note: NO assistant tool_calls turn here.
            {"role": "tool", "name": "t", "tool_call_id": "ghost", "content": "{}"},
            {"role": "user", "content": "y"},
        ],
        "scratchpad": {},
    }
    mem = AgentMemory.from_dict(payload)
    msgs = mem.get_messages()
    assert [m["role"] for m in msgs] == ["user", "user"]


def test_from_dict_keeps_paired_tool_messages():
    payload = {
        "messages": [
            {"role": "user", "content": "x"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "abc", "type": "function",
                     "function": {"name": "t", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "name": "t", "tool_call_id": "abc", "content": "{}"},
        ],
        "scratchpad": {},
    }
    mem = AgentMemory.from_dict(payload)
    roles = [m["role"] for m in mem.get_messages()]
    assert roles == ["user", "assistant", "tool"]


# ---------------------------------------------------------------------------
# Tool result truncation
# ---------------------------------------------------------------------------


def test_tool_result_is_truncated():
    mem = AgentMemory(tool_result_max_chars=100)
    big = "x" * 5000
    mem.add_tool_result("t", big, tool_call_id="c1")
    stored = mem.get_messages()[0]["content"]
    assert len(stored) < 5000
    assert "truncated" in stored


def test_tool_result_truncation_disabled_with_zero():
    mem = AgentMemory(tool_result_max_chars=0)
    big = "x" * 5000
    mem.add_tool_result("t", big, tool_call_id="c1")
    stored = mem.get_messages()[0]["content"]
    assert stored == big


# ---------------------------------------------------------------------------
# Context update from tool calls (D.2 – beyond run_eda_stage)
# ---------------------------------------------------------------------------


def test_update_context_from_arguments():
    mem = AgentMemory()
    mem.update_context_from_tool(
        {"design_name": "aes", "pdk": "sky130hd", "design_config": "/p/c.mk"},
        None,
    )
    ctx = mem.context()
    assert ctx["design_name"] == "aes"
    assert ctx["pdk"] == "sky130hd"
    assert ctx["config_path"] == "/p/c.mk"


def test_update_context_from_tool_result_string():
    mem = AgentMemory()
    mem.update_context_from_tool(
        None,
        json.dumps({"design_name": "gcd", "run_id": 42}),
    )
    ctx = mem.context()
    assert ctx["design_name"] == "gcd"
    assert ctx["run_id"] == 42


def test_context_update_overwrites_with_latest():
    mem = AgentMemory()
    mem.update_context_from_tool({"design_name": "aes"}, None)
    mem.update_context_from_tool({"design_name": "gcd"}, None)
    assert mem.context()["design_name"] == "gcd"


# ---------------------------------------------------------------------------
# Token budget view
# ---------------------------------------------------------------------------


def test_get_messages_respects_token_budget():
    mem = AgentMemory()
    for i in range(10):
        mem.add_user("a" * 400)  # ~100 tokens each
    full = mem.get_messages()
    trimmed = mem.get_messages(max_tokens=200)
    assert len(trimmed) < len(full)


def test_get_messages_token_budget_preserves_system_prompt():
    mem = AgentMemory()
    for _ in range(20):
        mem.add_user("a" * 800)
    trimmed = mem.get_messages(system_prompt="SYS", max_tokens=50)
    assert trimmed[0]["role"] == "system"
    assert trimmed[0]["content"] == "SYS"


# ---------------------------------------------------------------------------
# forget vs clear
# ---------------------------------------------------------------------------


def test_clear_keeps_scratchpad():
    mem = AgentMemory()
    mem.add_user("x")
    mem.set("design_name", "aes")
    mem.clear()
    assert len(mem) == 0
    assert mem.context()["design_name"] == "aes"


def test_forget_wipes_everything():
    mem = AgentMemory()
    mem.add_user("x")
    mem.set("design_name", "aes")
    mem.set("_internal_thing", 1)
    mem.forget()
    assert len(mem) == 0
    assert mem.context() == {}
    assert mem.get("_internal_thing") is None


# ---------------------------------------------------------------------------
# Byte budget
# ---------------------------------------------------------------------------


def test_shrink_to_byte_budget():
    mem = AgentMemory()
    for i in range(10):
        mem.add_user("x" * 1000)
    mem.shrink_to_byte_budget(2_000)
    # We dropped enough that the JSON payload now fits in 2 KB.
    payload = json.dumps([AgentMemory._serialise(m) for m in mem._history])
    assert len(payload.encode()) <= 2_000


# ---------------------------------------------------------------------------
# Backwards compatibility: old-format from_messages still works
# ---------------------------------------------------------------------------


def test_from_messages_backwards_compatible():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    mem = AgentMemory.from_messages(messages)
    assert len(mem) == 2
    assert mem.context() == {}


def test_message_dataclass_signature():
    # Importing Message must still work for callers that use it directly.
    m = Message(role="user", content="hi")
    assert m.role == "user"
