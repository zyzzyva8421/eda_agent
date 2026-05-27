from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from eda_agent.agent.custom_tools import (
    CustomToolConfigError,
    load_custom_tools,
    load_custom_tools_from_entry_points,
)
from eda_agent.agent.tools import _load_custom_tool_bindings, execute_tool


def _write_custom_tools(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_custom_tools_and_execute(tmp_path: Path):
    cfg = tmp_path / "custom_tools.json"
    _write_custom_tools(
        cfg,
        {
            "tools": [
                {
                    "name": "echo_note",
                    "description": "Echo note text",
                    "parameters": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    "command": ["echo", "{message}"],
                    "timeout_sec": 5,
                }
            ]
        },
    )

    schemas, dispatch, policies, sources = load_custom_tools(cfg)
    assert len(schemas) == 1
    assert "echo_note" in dispatch
    assert policies["echo_note"]["risk_level"] == "safe"
    assert sources["echo_note"].startswith("json:")

    result = dispatch["echo_note"](message="hello-custom")
    assert result["ok"] is True
    assert result["stdout"].strip() == "hello-custom"


def test_load_custom_tools_rejects_invalid_schema(tmp_path: Path):
    cfg = tmp_path / "bad_custom_tools.json"
    _write_custom_tools(
        cfg,
        {
            "tools": [
                {
                    "name": "bad_tool",
                    "description": "invalid",
                    "parameters": {"type": "array"},
                    "command": ["echo", "x"],
                }
            ]
        },
    )

    with pytest.raises(CustomToolConfigError):
        load_custom_tools(cfg)


def test_load_custom_tools_skip_reserved_name(tmp_path: Path):
    cfg = tmp_path / "custom_tools_reserved.json"
    _write_custom_tools(
        cfg,
        {
            "tools": [
                {
                    "name": "query_timing",
                    "description": "conflict with built-in",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "string"}},
                        "required": [],
                    },
                    "command": ["echo", "{x}"],
                }
            ]
        },
    )

    schemas, dispatch, policies, sources = load_custom_tools(
        cfg,
        reserved_names={"query_timing"},
    )
    assert schemas == []
    assert dispatch == {}
    assert policies == {}
    assert sources == {}


def test_load_custom_tools_allowlist_and_denylist(tmp_path: Path):
    cfg = tmp_path / "custom_tools_filter.json"
    _write_custom_tools(
        cfg,
        {
            "tools": [
                {
                    "name": "echo_allowed",
                    "description": "allowed tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    "command": ["echo", "{message}"],
                },
                {
                    "name": "echo_denied",
                    "description": "denied tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    "command": ["echo", "{message}"],
                },
            ]
        },
    )

    schemas, dispatch, _, _ = load_custom_tools(
        cfg,
        allowlist={"echo_allowed", "echo_denied"},
        denylist={"echo_denied"},
    )
    loaded_names = {item["function"]["name"] for item in schemas}
    assert loaded_names == {"echo_allowed"}
    assert set(dispatch.keys()) == {"echo_allowed"}


def test_load_custom_tools_from_entry_points():
    class _EP:
        name = "dummy_plugin"

        def load(self):
            return lambda: {
                "name": "plugin_tool",
                "description": "tool from plugin",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
                "permissions": {"risk_level": "warn", "requires_confirmation": True},
                "callable": lambda x: {"ok": True, "x": x},
            }

    with patch("eda_agent.agent.custom_tools.entry_points", return_value=[_EP()]):
        schemas, dispatch, policies, sources = load_custom_tools_from_entry_points()

    assert schemas and schemas[0]["function"]["name"] == "plugin_tool"
    assert "plugin_tool" in dispatch
    assert policies["plugin_tool"]["risk_level"] == "warn"
    assert policies["plugin_tool"]["requires_confirmation"] is True
    assert sources["plugin_tool"] == "entrypoint:dummy_plugin"


def test_tools_module_custom_binding_and_execute(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "custom_tools_runtime.json"
    _write_custom_tools(
        cfg,
        {
            "tools": [
                {
                    "name": "echo_runtime",
                    "description": "Echo text for runtime test",
                    "parameters": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    "command": ["echo", "{message}"],
                }
            ]
        },
    )

    monkeypatch.setattr("eda_agent.agent.tools.settings.custom_tools_file", str(cfg))

    monkeypatch.setattr("eda_agent.agent.tools.settings.custom_tools_allowlist", "")
    monkeypatch.setattr("eda_agent.agent.tools.settings.custom_tools_denylist", "")
    monkeypatch.setattr("eda_agent.agent.tools.settings.custom_tools_enable_entrypoints", False)

    schemas, dispatch, policies, sources = _load_custom_tool_bindings()
    assert schemas and schemas[0]["function"]["name"] == "echo_runtime"
    assert "echo_runtime" in dispatch
    assert policies["echo_runtime"]["risk_level"] == "safe"
    assert sources["echo_runtime"].startswith("json:")

    with patch.dict("eda_agent.agent.tools._TOOL_DISPATCH", dispatch, clear=False):
        result = json.loads(
            execute_tool("echo_runtime", {"message": "hello-runtime"})
        )

    assert result["ok"] is True
    assert result["stdout"].strip() == "hello-runtime"
