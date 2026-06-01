from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner


def _mock_response(content: str = "ok") -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ]
    }
    return response


def test_call_llm_retries_with_reduced_context_on_timeout():
    planner = Planner(api_key="dummy", model="dummy")
    planner._input_max_tokens = 123
    planner._timeout_retry_input_max_tokens = 45

    mem = AgentMemory()
    mem.set(
        "_similar_cases",
        [
            {
                "design_name": "aes",
                "symptoms": "overflow",
                "root_cause": "huge prompt",
                "actions": ["trim history"],
            }
        ],
    )

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = [httpx.ReadTimeout("timed out"), _mock_response("retried")]

    with (
        patch("httpx.Client", return_value=client),
        patch.object(mem, "get_messages", wraps=mem.get_messages) as get_messages,
    ):
        response = planner._call_llm(mem)

    assert response["choices"][0]["message"]["content"] == "retried"
    assert len(get_messages.call_args_list) == 2

    initial_call, retry_call = get_messages.call_args_list
    assert initial_call.kwargs["max_tokens"] == 123
    assert "Similar Historical Cases" in initial_call.kwargs["system_prompt"]
    assert retry_call.kwargs["max_tokens"] == 45
    assert "Similar Historical Cases" not in retry_call.kwargs["system_prompt"]


def test_call_llm_raises_timeout_error_after_retry_exhausted():
    planner = Planner(api_key="dummy", model="dummy")

    mem = AgentMemory()
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = [httpx.ReadTimeout("first"), httpx.ReadTimeout("second")]

    with patch("httpx.Client", return_value=client), pytest.raises(
        TimeoutError, match="LLM request timed out"
    ):
        planner._call_llm(mem)
