"""Runtime loader for user-defined custom tools.

Custom tools are declared in a JSON file and mapped to OpenAI-style function
schemas plus executable callables.

Example file:
{
  "tools": [
    {
      "name": "echo_note",
      "description": "Echo a note in terminal.",
      "parameters": {
        "type": "object",
        "properties": {
          "message": {"type": "string", "description": "text to echo"}
        },
        "required": ["message"]
      },
      "command": ["echo", "{message}"],
      "timeout_sec": 10
    }
  ]
}
"""

from __future__ import annotations

import json
import logging
import subprocess
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_MAX_TIMEOUT_SEC = 600
_DEFAULT_TIMEOUT_SEC = 30
_RISK_LEVELS = {"safe", "warn", "block"}

CustomToolPolicies = dict[str, dict[str, Any]]
CustomToolSources = dict[str, str]


class CustomToolConfigError(ValueError):
    """Raised when custom tools config is invalid."""


def _should_include_tool(
    name: str,
    *,
    allowlist: set[str] | None,
    denylist: set[str] | None,
) -> bool:
    if denylist and name in denylist:
        logger.info("Skip custom tool '%s': in denylist", name)
        return False
    if allowlist and name not in allowlist:
        logger.info("Skip custom tool '%s': not in allowlist", name)
        return False
    return True


def _validate_parameters_schema(raw: Any, tool_name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CustomToolConfigError(f"custom tool '{tool_name}' parameters must be an object")

    if raw.get("type") != "object":
        raise CustomToolConfigError(
            f"custom tool '{tool_name}' parameters.type must be 'object'"
        )

    properties = raw.get("properties")
    if not isinstance(properties, dict):
        raise CustomToolConfigError(
            f"custom tool '{tool_name}' parameters.properties must be an object"
        )

    required = raw.get("required", [])
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        raise CustomToolConfigError(
            f"custom tool '{tool_name}' parameters.required must be a string list"
        )

    return {"type": "object", "properties": properties, "required": required}


def _validate_permissions(raw: Any, tool_name: str) -> dict[str, Any]:
    if raw is None:
        return {"risk_level": "safe", "requires_confirmation": False}
    if not isinstance(raw, dict):
        raise CustomToolConfigError(
            f"custom tool '{tool_name}' permissions must be an object"
        )

    risk_level = raw.get("risk_level", "safe")
    if risk_level not in _RISK_LEVELS:
        raise CustomToolConfigError(
            f"custom tool '{tool_name}' permissions.risk_level must be one of "
            f"{sorted(_RISK_LEVELS)}"
        )

    requires_confirmation = raw.get("requires_confirmation", False)
    if not isinstance(requires_confirmation, bool):
        raise CustomToolConfigError(
            f"custom tool '{tool_name}' permissions.requires_confirmation must be bool"
        )

    return {
        "risk_level": risk_level,
        "requires_confirmation": requires_confirmation,
    }


def _validate_entrypoint_tool_spec(spec: Any, ep_name: str) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise CustomToolConfigError(
            f"entry point '{ep_name}' must return a dict or list[dict]"
        )

    required = {"name", "description", "parameters", "callable"}
    missing = required - set(spec.keys())
    if missing:
        raise CustomToolConfigError(
            f"entry point '{ep_name}' spec missing fields: {sorted(missing)}"
        )
    if not callable(spec["callable"]):
        raise CustomToolConfigError(
            f"entry point '{ep_name}' field 'callable' must be callable"
        )
    return spec


def _build_runner(
    *,
    name: str,
    command_tokens: list[str],
    allowed_params: set[str],
    timeout_sec: int,
) -> Callable[..., dict[str, Any]]:
    def _runner(**kwargs: Any) -> dict[str, Any]:
        unknown = sorted(set(kwargs) - allowed_params)
        if unknown:
            raise ValueError(
                f"custom tool '{name}' received unknown args: {', '.join(unknown)}"
            )

        render_args = {k: "" if v is None else str(v) for k, v in kwargs.items()}
        argv: list[str] = []
        for token in command_tokens:
            try:
                argv.append(token.format(**render_args))
            except KeyError as exc:
                missing = exc.args[0]
                raise ValueError(
                    f"custom tool '{name}' missing required placeholder value: {missing}"
                ) from exc

        cp = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )

        return {
            "tool": name,
            "command": argv,
            "exit_code": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "ok": cp.returncode == 0,
        }

    return _runner


def load_custom_tools(
    file_path: str | Path,
    *,
    reserved_names: set[str] | None = None,
    allowlist: set[str] | None = None,
    denylist: set[str] | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Callable[..., Any]],
    CustomToolPolicies,
    CustomToolSources,
]:
    """Load custom tools from JSON file.

    Returns:
        (tool_schemas, tool_dispatch_entries)
    """
    p = Path(file_path)
    if not p.exists():
        raise CustomToolConfigError(f"custom tools file does not exist: {p}")

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CustomToolConfigError(f"invalid JSON in custom tools file: {p}") from exc

    if not isinstance(raw, dict):
        raise CustomToolConfigError("custom tools root must be a JSON object")

    tools = raw.get("tools")
    if not isinstance(tools, list):
        raise CustomToolConfigError("custom tools JSON must contain list field 'tools'")

    blocked_names = reserved_names or set()
    schemas: list[dict[str, Any]] = []
    dispatch: dict[str, Callable[..., Any]] = {}
    policies: CustomToolPolicies = {}
    sources: CustomToolSources = {}

    for item in tools:
        if not isinstance(item, dict):
            raise CustomToolConfigError("each custom tool must be an object")

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CustomToolConfigError("custom tool name must be a non-empty string")
        if name in blocked_names:
            logger.warning("Skip custom tool '%s': conflicts with built-in tool", name)
            continue
        if not _should_include_tool(name, allowlist=allowlist, denylist=denylist):
            continue

        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            raise CustomToolConfigError(
                f"custom tool '{name}' description must be a non-empty string"
            )

        parameters = _validate_parameters_schema(item.get("parameters"), name)
        permissions = _validate_permissions(item.get("permissions"), name)

        command = item.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(token, str) for token in command
        ):
            raise CustomToolConfigError(
                f"custom tool '{name}' command must be a non-empty string list"
            )

        timeout_raw = item.get("timeout_sec", _DEFAULT_TIMEOUT_SEC)
        if not isinstance(timeout_raw, int) or timeout_raw <= 0:
            raise CustomToolConfigError(
                f"custom tool '{name}' timeout_sec must be a positive integer"
            )
        timeout_sec = min(timeout_raw, _MAX_TIMEOUT_SEC)

        properties = parameters.get("properties", {})
        allowed_params = {str(k) for k in properties.keys()}

        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
        dispatch[name] = _build_runner(
            name=name,
            command_tokens=command,
            allowed_params=allowed_params,
            timeout_sec=timeout_sec,
        )
        policies[name] = permissions
        sources[name] = f"json:{p}"

    return schemas, dispatch, policies, sources


def load_custom_tools_from_entry_points(
    *,
    group: str = "eda_agent.custom_tools",
    reserved_names: set[str] | None = None,
    allowlist: set[str] | None = None,
    denylist: set[str] | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Callable[..., Any]],
    CustomToolPolicies,
    CustomToolSources,
]:
    """Load custom tools from Python entry points.

    Each entry point must resolve to one of:
    - dict spec
    - list[dict] specs
    - callable returning dict/list[dict]
    """
    schemas: list[dict[str, Any]] = []
    dispatch: dict[str, Callable[..., Any]] = {}
    policies: CustomToolPolicies = {}
    sources: CustomToolSources = {}
    blocked_names = reserved_names or set()

    eps = entry_points(group=group)
    for ep in eps:
        try:
            loaded = ep.load()
            value = loaded() if callable(loaded) else loaded
        except Exception:
            logger.exception("Failed to load custom tool entry point '%s'", ep.name)
            continue

        specs = value if isinstance(value, list) else [value]
        for raw_spec in specs:
            spec = _validate_entrypoint_tool_spec(raw_spec, ep.name)
            name = str(spec["name"])

            if name in blocked_names or name in dispatch:
                logger.warning(
                    "Skip entrypoint custom tool '%s': conflicts with existing tool", name
                )
                continue
            if not _should_include_tool(name, allowlist=allowlist, denylist=denylist):
                continue

            description = str(spec["description"])
            parameters = _validate_parameters_schema(spec["parameters"], name)
            permissions = _validate_permissions(spec.get("permissions"), name)
            fn = spec["callable"]

            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
            dispatch[name] = fn
            policies[name] = permissions
            sources[name] = f"entrypoint:{ep.name}"

    return schemas, dispatch, policies, sources
