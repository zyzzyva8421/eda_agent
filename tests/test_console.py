"""Tests for the console / spinner helpers."""

from __future__ import annotations

import io

from eda_agent.console import Console, Spinner, style, truncate


def test_truncate_basic():
    assert truncate("hello") == "hello"
    assert truncate("a" * 300, limit=10).endswith("…")
    assert len(truncate("a" * 300, limit=10)) == 10


def test_truncate_collapses_newlines():
    assert truncate("foo\nbar") == "foo bar"


def test_style_no_color_on_non_tty():
    buf = io.StringIO()
    assert style("hi", "red", stream=buf) == "hi"  # not a TTY, no escapes


def test_console_quiet_suppresses_info_and_events():
    out, err = io.StringIO(), io.StringIO()
    c = Console(stream=out, err_stream=err, quiet=True)
    c.info("ignored")
    c.event("iteration_start", {"iteration": 1})
    c.event("tool_call", {"name": "x", "arguments": {"a": 1}})
    assert out.getvalue() == ""

    # But errors still flow.
    c.error("boom")
    assert "Error" in err.getvalue()


def test_console_event_renders_tool_call_with_truncation():
    out = io.StringIO()
    c = Console(stream=out, err_stream=io.StringIO(), show_events=True)
    long_args = {"path": "x" * 500}
    c.event("tool_call", {"name": "run_eda_flow", "arguments": long_args})
    text = out.getvalue()
    assert "run_eda_flow" in text
    # The truncated preview ends with the ellipsis character.
    assert "…" in text


def test_console_event_async_submission_emits_tip():
    out = io.StringIO()
    c = Console(stream=out, err_stream=io.StringIO(), show_events=True)
    c.event("async_submission", {"job_id": "abc-123"})
    text = out.getvalue()
    assert "abc-123" in text
    assert "eda-agent logs" in text
    assert "--follow" in text


def test_console_streaming_tokens_print_inline_and_agent_terminates():
    out = io.StringIO()
    c = Console(stream=out, err_stream=io.StringIO(), show_events=False)
    c.event("token", {"content": "Hello "})
    c.event("token", {"content": "world"})
    # Final reply call should just terminate the stream.
    c.agent("ignored-because-streamed")
    text = out.getvalue()
    assert "Hello world" in text
    # The text we passed to agent() should NOT be re-printed.
    assert "ignored-because-streamed" not in text


def test_spinner_is_noop_on_non_tty():
    out = io.StringIO()
    c = Console(stream=out, err_stream=io.StringIO())
    with Spinner(c, text="thinking"):
        pass
    # No TTY → no spinner output written.
    assert out.getvalue() == ""


def test_console_tool_events_update_spinner_text_even_when_events_hidden():
    out = io.StringIO()
    c = Console(stream=out, err_stream=io.StringIO(), show_events=False)
    spinner = Spinner(c, text="thinking")
    c.attach_spinner(spinner)
    c.event("tool_call", {"name": "run_eda_stage", "arguments": {}})
    assert spinner._text == "running run_eda_stage"
    c.event("tool_result", {"name": "run_eda_stage", "ok": True})
    assert spinner._text == "thinking"
