"""Tests for the agent memory module."""

from __future__ import annotations

import json

from eda_agent.agent.memory import AgentMemory, Message


def test_add_and_retrieve():
    mem = AgentMemory()
    mem.add_user("Hello")
    mem.add_assistant("Hi there!")
    msgs = mem.get_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_system_prompt_prepended():
    mem = AgentMemory()
    mem.add_user("test")
    msgs = mem.get_messages(system_prompt="You are helpful.")
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "You are helpful."
    assert msgs[1]["role"] == "user"


def test_tool_result():
    mem = AgentMemory()
    mem.add_tool_result("query_timing", '{"wns": -0.3}', tool_call_id="abc")
    msgs = mem.get_messages()
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["name"] == "query_timing"
    assert msgs[0]["tool_call_id"] == "abc"


def test_max_messages_bounded():
    mem = AgentMemory(max_messages=3)
    for i in range(5):
        mem.add_user(f"msg {i}")
    assert len(mem) == 3


def test_scratchpad():
    mem = AgentMemory()
    mem.set("run_id", 42)
    assert mem.get("run_id") == 42
    assert mem.get("missing", "default") == "default"


def test_clear():
    mem = AgentMemory()
    mem.add_user("hello")
    mem.clear()
    assert len(mem) == 0


# ── extract_design_context ─────────────────────────────────────────────


def test_extract_design_context_empty():
    """Returns empty dict when scratchpad has no design context."""
    mem = AgentMemory()
    assert mem.extract_design_context() == {}


def test_extract_design_context_from_scratchpad():
    """Returns context from scratchpad (canonical source)."""
    mem = AgentMemory()
    mem.set("design_name", "aes")
    mem.set("pdk", "sky130hd")
    mem.set("config_path", "/designs/aes/config.mk")
    ctx = mem.extract_design_context()
    assert ctx == {
        "design_name": "aes",
        "pdk": "sky130hd",
        "config_path": "/designs/aes/config.mk",
    }


def test_extract_design_context_partial():
    """Returns only non-empty entries."""
    mem = AgentMemory()
    mem.set("design_name", "gcd")
    # pdk and config_path not set
    ctx = mem.extract_design_context()
    assert ctx == {"design_name": "gcd"}


def test_extract_design_context_ignores_tool_history():
    """Does NOT parse tool result strings – only uses scratchpad."""
    mem = AgentMemory()
    # Add a tool result with design_name embedded, but scratchpad is empty
    result = json.dumps({"design_name": "fake_design", "pdk": "fake_pdk"})
    mem.add_tool_result("run_eda_stage", result)
    # Should NOT extract from the JSON string
    assert mem.extract_design_context() == {}


def test_extract_design_context_ignores_invalid_json_in_history():
    """Malformed JSON in tool results does not break extraction."""
    mem = AgentMemory()
    mem.set("design_name", "riscv_core")
    mem.add_tool_result("run_eda_flow", "not valid json{{{")
    # Should still return the scratchpad value, ignoring the garbage
    assert mem.extract_design_context() == {"design_name": "riscv_core"}


# ── get_state / from_state  (DB persistence across HTTP requests) ───────


def test_get_state_roundtrip():
    """get_state() → from_state() preserves messages + scratchpad."""
    mem = AgentMemory()
    mem.add_user("run place on gcd")
    mem.add_assistant("OK, running place")
    mem.set("design_name", "gcd")
    mem.set("pdk", "sky130hd")

    state = mem.get_state()
    assert "messages" in state
    assert "scratchpad" in state
    assert state["scratchpad"]["design_name"] == "gcd"
    assert state["scratchpad"]["pdk"] == "sky130hd"

    mem2 = AgentMemory.from_state(state)
    assert len(mem2) == 2
    assert mem2.get("design_name") == "gcd"
    assert mem2.get("pdk") == "sky130hd"
    assert mem2.extract_design_context() == {
        "design_name": "gcd",
        "pdk": "sky130hd",
    }


def test_from_state_legacy_message_list():
    """Backward compat: from_state accepts a plain message list (old format)."""
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    mem = AgentMemory.from_state(messages)
    assert len(mem) == 2
    assert mem.get("design_name") is None
    assert mem.extract_design_context() == {}


def test_from_state_empty():
    """from_state with empty dict returns empty memory."""
    mem = AgentMemory.from_state({})
    assert len(mem) == 0
    assert mem.extract_design_context() == {}


def test_get_state_preserves_design_context_after_scratchpad_fill():
    """Simulates real planner flow: set scratchpad → get_state → from_state."""
    mem = AgentMemory()
    mem.add_user("optimize place on aes")
    mem.set("design_name", "aes")
    mem.set("pdk", "sky130hd")
    mem.set("config_path", "/flows/aes/config.mk")

    state = mem.get_state()
    mem2 = AgentMemory.from_state(state)
    ctx = mem2.extract_design_context()
    assert ctx == {
        "design_name": "aes",
        "pdk": "sky130hd",
        "config_path": "/flows/aes/config.mk",
    }


def test_from_state_skips_non_dict_entries():
    """Non-dict entries (e.g. strings, numbers) in messages are skipped."""
    state = {
        "messages": [
            {"role": "user", "content": "hello"},
            "this is not a dict",
            42,
            {"role": "assistant", "content": "hi"},
        ],
        "scratchpad": {"design_name": "gcd"},
    }
    mem = AgentMemory.from_state(state)
    assert len(mem) == 2  # non-dict entries skipped
    assert mem.extract_design_context() == {"design_name": "gcd"}
