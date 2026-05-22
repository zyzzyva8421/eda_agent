"""LangSmith tracing integration for EDA Agent.

Usage:
    from eda_agent.tracing import get_tracer, tracer_wrapper

    # Setup (call once at startup)
    if settings.langsmith_enabled:
        get_tracer(project_name=settings.langsmith_project)

    # Wrap LLM calls
    def call_llm(...):
        response = make_http_request(...)
        return tracer_wrapper(response, "call_minimax", input_data={...})
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import wraps
from typing import Any, Callable

from langsmith import Client

from eda_agent.config import settings

# Global tracer client
_tracer_client: Client | None = None


def get_tracer(project_name: str = "eda-agent") -> Client:
    """Initialize LangSmith client."""
    global _tracer_client
    if not settings.langsmith_api_key:
        raise ValueError(
            "LANGSMITH_API_KEY not set. Get it from https://smith.langchain.com/"
        )
    _tracer_client = Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
    )
    return _tracer_client


def init_tracing() -> Client | None:
    """Initialize tracing if enabled in settings."""
    if not settings.langsmith_enabled:
        return None
    return get_tracer(settings.langsmith_project)


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled."""
    return settings.langsmith_enabled and bool(settings.langsmith_api_key)


def tracer_wrapper(
    response: dict[str, Any],
    name: str,
    input_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap an LLM call response with tracing metadata.

    Args:
        response: The raw API response
        name: Operation name (e.g., "call_minimax", "planner.step")
        input_data: Optional input payload
        metadata: Optional metadata to attach

    Returns:
        Response with added tracing info
    """
    if not is_tracing_enabled() or _tracer_client is None:
        return response

    try:
        # Extract standard fields from response
        model = response.get("model", "")
        usage = response.get("usage", {})
        choices = response.get("choices", [{}])
        output_text = ""
        if choices:
            msg = choices[0].get("message", {})
            output_text = msg.get("content", "")

        # Create run metadata
        run_data: dict[str, Any] = {
            "name": name,
            "run_type": "llm",
            "inputs": input_data or {},
            "outputs": {"text": output_text[:500]},  # Truncate for storage
            "extra": {
                "model": model,
                "usage": usage,
                **(metadata or {}),
            },
        }

        # Log to LangSmith
        _tracer_client.create_run(**run_data)

        # Attach metadata to response for later reference
        response["_tracing"] = {
            "project": settings.langsmith_project,
            "name": name,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception:
        pass  # Non-blocking

    return response


def trace_llm_call(func: Callable) -> Callable:
    """Decorator to trace an LLM call function.

    Usage:
        @trace_llm_call
        def call_minimax(messages, ...):
            ...
            return response
    """
    if not is_tracing_enabled():
        return func

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = datetime.utcnow()

        # Capture input
        input_data = {}
        if args:
            input_data = {"args_len": len(args)}
        if kwargs:
            input_data.update(kwargs)

        # Make the call
        response = func(*args, **kwargs)

        # Wrap with tracing
        tracer_wrapper(response, func.__name__, input_data={"call": func.__name__})

        return response

    return wrapper


# Convenience function to trace a chat completion
def trace_chat(
    messages: list[dict[str, Any]],
    response: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """Trace a chat completion call.

    Args:
        messages: Input messages
        response: API response
        model: Model name

    Returns:
        Response with tracing metadata
    """
    return tracer_wrapper(
        response,
        "chat_completion",
        input_data={
            "messages_count": len(messages),
            "model": model,
        },
        metadata={"model": model},
    )