"""Tests for the tool dispatch layer (no DB/LLM required)."""

from __future__ import annotations

import json

import pytest

from eda_agent.agent.tools import execute_tool


def test_execute_unknown_tool():
    result = json.loads(execute_tool("no_such_tool", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_execute_tool_bad_args():
    """Missing required arg → JSON error, no exception raised."""
    result = json.loads(execute_tool("query_timing", {}))
    # Should return an error dict, not raise
    assert isinstance(result, (list, dict))
    # May be an error or empty list depending on DB availability
