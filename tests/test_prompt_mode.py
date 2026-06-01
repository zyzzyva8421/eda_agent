"""Tests for Gemma4 prompt-mode tool-calling helpers in Planner."""

from __future__ import annotations

import json

import pytest

from eda_agent.agent.planner import Planner, _TOOL_CALL_RE
from eda_agent.agent.tool_schemas import TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# _TOOL_CALL_RE regex
# ---------------------------------------------------------------------------


def test_tool_call_re_matches_simple():
    text = '<tool_call>\n{"name": "foo", "arguments": {}}\n</tool_call>'
    m = _TOOL_CALL_RE.search(text)
    assert m is not None
    payload = json.loads(m.group(1))
    assert payload["name"] == "foo"


def test_tool_call_re_matches_inline():
    text = '<tool_call>{"name": "bar", "arguments": {"x": 1}}</tool_call>'
    m = _TOOL_CALL_RE.search(text)
    assert m is not None
    payload = json.loads(m.group(1))
    assert payload["name"] == "bar"


def test_tool_call_re_no_match():
    assert _TOOL_CALL_RE.search("plain text with no tool call") is None


def test_tool_call_re_multiple():
    text = (
        '<tool_call>{"name": "a", "arguments": {}}</tool_call> '
        'done '
        '<tool_call>{"name": "b", "arguments": {}}</tool_call>'
    )
    matches = _TOOL_CALL_RE.findall(text)
    assert len(matches) == 2


# ---------------------------------------------------------------------------
# _parse_tool_calls_from_text
# ---------------------------------------------------------------------------


def test_parse_tool_calls_single():
    p = Planner()
    text = (
        "Let me check.\n"
        '<tool_call>\n{"name": "query_timing", "arguments": {"design_name": "gcd"}}\n</tool_call>'
    )
    calls = p._parse_tool_calls_from_text(text)
    assert len(calls) == 1
    assert calls[0]["type"] == "function"
    assert calls[0]["function"]["name"] == "query_timing"
    assert json.loads(calls[0]["function"]["arguments"]) == {"design_name": "gcd"}
    # id should be a non-empty string
    assert calls[0]["id"]


def test_parse_tool_calls_multiple():
    p = Planner()
    text = (
        '<tool_call>{"name": "a", "arguments": {"x": 1}}</tool_call>\n'
        '<tool_call>{"name": "b", "arguments": {"y": 2}}</tool_call>'
    )
    calls = p._parse_tool_calls_from_text(text)
    assert len(calls) == 2
    assert calls[0]["function"]["name"] == "a"
    assert calls[1]["function"]["name"] == "b"


def test_parse_tool_calls_empty():
    p = Planner()
    assert p._parse_tool_calls_from_text("no tools here") == []


def test_parse_tool_calls_bad_json():
    p = Planner()
    # Malformed JSON inside tag — should be skipped gracefully
    text = "<tool_call>{bad json}</tool_call>"
    calls = p._parse_tool_calls_from_text(text)
    assert calls == []


def test_parse_tool_calls_arguments_is_string():
    """arguments field is preserved as a JSON-encoded string, not a dict."""
    p = Planner()
    text = '<tool_call>{"name": "foo", "arguments": {"k": "v"}}</tool_call>'
    calls = p._parse_tool_calls_from_text(text)
    assert isinstance(calls[0]["function"]["arguments"], str)
    assert json.loads(calls[0]["function"]["arguments"]) == {"k": "v"}


def test_parse_tool_calls_arguments_non_dict_are_json_encoded():
    p = Planner()
    text = '<tool_call>{"name": "foo", "arguments": "raw-string"}</tool_call>'
    calls = p._parse_tool_calls_from_text(text)
    assert calls[0]["function"]["arguments"] == '"raw-string"'
    assert json.loads(calls[0]["function"]["arguments"]) == "raw-string"


# ---------------------------------------------------------------------------
# _messages_for_prompt_mode
# ---------------------------------------------------------------------------


def _make_messages():
    return [
        {"role": "system", "content": "You are an EDA assistant."},
        {"role": "user", "content": "What is the WNS?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "query_timing",
                        "arguments": json.dumps({"design_name": "gcd"}),
                    }
                }
            ],
        },
        {"role": "tool", "name": "query_timing", "content": '{"wns": -0.1}'},
        {"role": "assistant", "content": "The WNS is -0.1 ns."},
    ]


def test_messages_for_prompt_mode_preserves_system_and_user():
    p = Planner()
    result = p._messages_for_prompt_mode(_make_messages())
    assert result[0] == {"role": "system", "content": "You are an EDA assistant."}
    assert result[1] == {"role": "user", "content": "What is the WNS?"}


def test_messages_for_prompt_mode_assistant_tool_calls_converted():
    p = Planner()
    result = p._messages_for_prompt_mode(_make_messages())
    assistant_turn = result[2]
    assert assistant_turn["role"] == "assistant"
    assert "<tool_call>" in assistant_turn["content"]
    assert "query_timing" in assistant_turn["content"]
    # Should not contain raw tool_calls key
    assert "tool_calls" not in assistant_turn


def test_messages_for_prompt_mode_tool_result_becomes_user():
    p = Planner()
    result = p._messages_for_prompt_mode(_make_messages())
    tool_turn = result[3]
    assert tool_turn["role"] == "user"
    assert "Tool result for query_timing" in tool_turn["content"]
    assert '{"wns": -0.1}' in tool_turn["content"]


def test_messages_for_prompt_mode_final_assistant_unchanged():
    p = Planner()
    result = p._messages_for_prompt_mode(_make_messages())
    last = result[4]
    assert last["role"] == "assistant"
    assert last["content"] == "The WNS is -0.1 ns."


def test_messages_for_prompt_mode_assistant_text_and_tool_calls_both_preserved():
    p = Planner()
    messages = [
        {"role": "user", "content": "check"},
        {
            "role": "assistant",
            "content": "I will call a tool first.",
            "tool_calls": [
                {
                    "function": {
                        "name": "query_timing",
                        "arguments": json.dumps({"design_name": "gcd"}),
                    }
                }
            ],
        },
    ]

    result = p._messages_for_prompt_mode(messages)
    assert result[1]["role"] == "assistant"
    assert "I will call a tool first." in result[1]["content"]
    assert "<tool_call>" in result[1]["content"]
    assert "query_timing" in result[1]["content"]


def test_messages_for_prompt_mode_empty():
    p = Planner()
    assert p._messages_for_prompt_mode([]) == []


# ---------------------------------------------------------------------------
# _tools_to_system_appendix
# ---------------------------------------------------------------------------


def test_tools_to_system_appendix_contains_header():
    appendix = Planner._tools_to_system_appendix(TOOL_SCHEMAS)
    assert "Available" in appendix
    assert "<tool_call>" in appendix


def test_tools_to_system_appendix_lists_tool_names():
    appendix = Planner._tools_to_system_appendix(TOOL_SCHEMAS)
    # At least one well-known tool should appear
    assert "query_timing" in appendix


def test_tools_to_system_appendix_empty_tools():
    appendix = Planner._tools_to_system_appendix([])
    assert isinstance(appendix, str)


# ---------------------------------------------------------------------------
# _normalize_prompt_mode_response
# ---------------------------------------------------------------------------


def _make_raw_response(content: str, finish_reason: str = "stop"):
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ]
    }


def test_normalize_extracts_tool_calls():
    p = Planner()
    raw = _make_raw_response(
        'let me check\n<tool_call>\n{"name": "query_timing", "arguments": {"design_name": "gcd"}}\n</tool_call>'
    )
    norm = p._normalize_prompt_mode_response(raw)
    choice = norm["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert len(choice["message"]["tool_calls"]) == 1
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "query_timing"


def test_normalize_strips_tool_call_block_from_content():
    p = Planner()
    raw = _make_raw_response(
        'prefix text\n<tool_call>{"name": "foo", "arguments": {}}</tool_call>\nsuffix'
    )
    norm = p._normalize_prompt_mode_response(raw)
    content = norm["choices"][0]["message"]["content"]
    assert "<tool_call>" not in content
    assert "prefix text" in content


def test_normalize_no_tool_calls_unchanged():
    p = Planner()
    raw = _make_raw_response("Just a plain text answer.")
    norm = p._normalize_prompt_mode_response(raw)
    assert norm["choices"][0]["finish_reason"] == "stop"
    assert "tool_calls" not in norm["choices"][0]["message"]
    assert norm["choices"][0]["message"]["content"] == "Just a plain text answer."


def test_normalize_no_choices():
    p = Planner()
    raw = {"choices": []}
    norm = p._normalize_prompt_mode_response(raw)
    assert norm == {"choices": []}


def test_normalize_multiple_tool_calls():
    p = Planner()
    raw = _make_raw_response(
        '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
        '<tool_call>{"name": "b", "arguments": {"x": 1}}</tool_call>'
    )
    norm = p._normalize_prompt_mode_response(raw)
    assert len(norm["choices"][0]["message"]["tool_calls"]) == 2
