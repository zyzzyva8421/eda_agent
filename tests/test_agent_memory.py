"""Tests for the agent memory module."""

from __future__ import annotations

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
