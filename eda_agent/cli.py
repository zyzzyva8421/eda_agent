"""Interactive REPL CLI for EDA Agent.

Provides a readline-based conversational shell that lets the user chat directly
with the ReAct planner without going through the HTTP API.

Usage::

    eda-agent          # start REPL
    eda-agent-server   # start FastAPI/Uvicorn server (see pyproject.toml)

Commands inside the REPL
------------------------
    clear    – clear the current session memory
    history  – print the current session message history
    exit / quit / Ctrl-D / Ctrl-C  – exit
"""

from __future__ import annotations

import sys

try:
    import readline as _readline  # noqa: F401 – imported for side-effect (history)

    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner

_BANNER = """\
╔══════════════════════════════════════════════════════╗
║          EDA Agent  –  Interactive CLI               ║
║  Type 'help' for commands, 'exit' to quit.           ║
╚══════════════════════════════════════════════════════╝
"""

_HELP = """\
Built-in commands:
  clear    – reset session memory
  history  – show message history
  help     – show this help
  exit     – quit (also: quit, Ctrl-D, Ctrl-C)

Anything else is forwarded to the EDA ReAct agent.
"""


def _print_history(memory: AgentMemory) -> None:
    msgs = memory.get_messages()
    if not msgs:
        print("(empty session)")
        return
    for i, m in enumerate(msgs, 1):
        role = m.get("role", "?").upper()
        content = m.get("content") or ""
        print(f"[{i}] {role}: {content[:200]}")


def cli_repl() -> None:
    """Entry point for the ``eda-agent`` console script."""
    print(_BANNER)
    planner = Planner()
    memory = AgentMemory()

    while True:
        try:
            user_input = input("eda-agent> ").strip()
        except EOFError:
            print("\nGoodbye!")
            break
        except KeyboardInterrupt:
            print("\n(Interrupted – type 'exit' to quit)")
            continue

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit"):
            print("Goodbye!")
            break
        if cmd == "clear":
            memory.clear()
            print("Session cleared.")
            continue
        if cmd == "history":
            _print_history(memory)
            continue
        if cmd == "help":
            print(_HELP)
            continue

        try:
            reply = planner.run(user_input, memory=memory)
            print(f"\nAgent: {reply}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}\n", file=sys.stderr)
