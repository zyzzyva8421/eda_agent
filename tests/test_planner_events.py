"""Tests for the new Planner.on_event callback and streaming helper."""

from __future__ import annotations

import json
from unittest.mock import patch

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner


def _fake_llm_response_with_tool_call(tool_name: str = "noop_tool"):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps({"x": 1}),
                            },
                        }
                    ],
                },
            }
        ]
    }


def _fake_llm_response_final(text: str = "All done."):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ]
    }


def test_on_event_emits_iteration_tool_call_and_result():
    planner = Planner()
    events: list[tuple[str, dict]] = []

    responses = iter(
        [_fake_llm_response_with_tool_call("query_timing"), _fake_llm_response_final("Final answer.")]
    )

    with (
        patch.object(Planner, "_call_llm", side_effect=lambda *a, **kw: next(responses)),
        patch("eda_agent.agent.planner.execute_tool", return_value='{"ok": true}'),
    ):
        reply = planner.run(
            "hello",
            memory=AgentMemory(),
            on_event=lambda kind, payload: events.append((kind, payload)),
        )

    assert reply == "Final answer."
    kinds = [k for k, _ in events]
    assert kinds.count("iteration_start") == 2
    assert "tool_call" in kinds
    assert "tool_result" in kinds

    # tool_call payload should carry name + arguments.
    tool_call = next(p for k, p in events if k == "tool_call")
    assert tool_call["name"] == "query_timing"
    assert tool_call["arguments"] == {"x": 1}

    # tool_result payload should report success + duration.
    tool_result = next(p for k, p in events if k == "tool_result")
    assert tool_result["ok"] is True
    assert tool_result["name"] == "query_timing"
    assert "duration" in tool_result


def test_on_event_async_submission_emitted_for_submit_job():
    planner = Planner()
    events: list[tuple[str, dict]] = []

    response = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "submit_job",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
            }
        ]
    }
    submission_payload = json.dumps({"job_id": "job-42", "status": "pending"})

    with (
        patch.object(Planner, "_call_llm", return_value=response),
        patch("eda_agent.agent.planner.execute_tool", return_value=submission_payload),
    ):
        reply = planner.run(
            "submit something",
            memory=AgentMemory(),
            on_event=lambda kind, payload: events.append((kind, payload)),
        )

    assert "job-42" in reply
    submission_events = [p for k, p in events if k == "async_submission"]
    assert submission_events and submission_events[0]["job_id"] == "job-42"


def test_on_event_listener_errors_do_not_crash_planner():
    planner = Planner()

    def bad_listener(_kind, _payload):
        raise RuntimeError("buggy listener")

    with patch.object(
        Planner, "_call_llm", return_value=_fake_llm_response_final("ok")
    ):
        reply = planner.run("hi", memory=AgentMemory(), on_event=bad_listener)
    assert reply == "ok"


def test_run_mutates_passed_empty_memory_instance():
    planner = Planner()
    memory = AgentMemory()

    with patch.object(
        Planner, "_call_llm", return_value=_fake_llm_response_final("ok")
    ):
        reply = planner.run("hi", memory=memory)

    assert reply == "ok"
    msgs = memory.get_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hi"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "ok"
