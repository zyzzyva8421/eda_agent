"""Tests for AgentMemory.from_messages (session serialisation)."""

from __future__ import annotations

from eda_agent.agent.memory import AgentMemory


def test_from_messages_roundtrip():
    mem = AgentMemory()
    mem.add_user("hello")
    mem.add_assistant("hi there")
    mem.add_user("what is WNS?")

    messages = mem.get_messages()  # no system prompt
    mem2 = AgentMemory.from_messages(messages)

    assert len(mem2) == len(mem)
    restored = mem2.get_messages()
    for orig, rest in zip(messages, restored):
        assert orig["role"] == rest["role"]
        assert orig["content"] == rest["content"]


def test_from_messages_skips_system():
    messages = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "run route"},
    ]
    mem = AgentMemory.from_messages(messages)
    # Only the user message should be stored (system is injected at prompt time)
    assert len(mem) == 1
    msgs = mem.get_messages()
    assert msgs[0]["role"] == "user"


def test_from_messages_with_tool_calls():
    tool_call = {
        "id": "call_123",
        "type": "function",
        "function": {"name": "query_timing", "arguments": '{"design_name": "gcd"}'},
    }
    messages = [
        {"role": "user", "content": "check timing"},
        {"role": "assistant", "content": "", "tool_calls": [tool_call]},
        {
            "role": "tool",
            "name": "query_timing",
            "content": '{"summary": []}',
            "tool_call_id": "call_123",
        },
    ]
    mem = AgentMemory.from_messages(messages)
    restored = mem.get_messages()
    assert restored[1]["tool_calls"] == [tool_call]
    assert restored[2]["tool_call_id"] == "call_123"


def test_empty_memory_from_empty_messages():
    mem = AgentMemory.from_messages([])
    assert len(mem) == 0
