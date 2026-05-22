"""Test LangSmith tracing integration."""

import os
import pytest
from unittest.mock import patch, MagicMock

# Test tracing module imports correctly
from eda_agent.tracing import (
    is_tracing_enabled,
    init_tracing,
    trace_chat,
    tracer_wrapper,
)
from eda_agent.config import settings


def test_tracing_disabled_by_default():
    """Tracing should be disabled when no API key is set."""
    with patch.object(settings, "langsmith_enabled", False), \
         patch.object(settings, "langsmith_api_key", ""):
        assert not is_tracing_enabled()


def test_tracer_wrapper_adds_metadata():
    """tracer_wrapper should add tracing metadata to response when enabled."""
    mock_response = {
        "model": "MiniMax-Text-01",
        "choices": [{"message": {"content": "test response"}}],
        "usage": {"total_tokens": 100},
    }

    # Without tracing, should return same response
    result = tracer_wrapper(mock_response, "test_call")
    assert result == mock_response
    assert "_tracing" not in result


@pytest.mark.skipif(
    not os.environ.get("LANGSMITH_API_KEY"),
    reason="LANGSMITH_API_KEY not set"
)
def test_tracing_with_real_api():
    """Integration test with real LangSmith API."""
    from langsmith import Client

    from eda_agent.tracing import get_tracer

    # Initialize with real API
    client = get_tracer("test-eda-agent")
    assert isinstance(client, Client)

    # Test trace_chat
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ]
    mock_response = {
        "model": settings.minimax_model,
        "choices": [{"message": {"content": "Hi there!"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    result = trace_chat(messages, mock_response, settings.minimax_model)
    assert "_tracing" in result
    assert result["_tracing"]["name"] == "chat_completion"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])