"""MiniMax ReAct planner.

Implements a ReAct (Reason + Act) loop using the MiniMax 2.5 Code Plan API
(OpenAI-compatible interface).

Loop
----
1. Build prompt from system instructions + memory history
2. Call MiniMax chat/completions with tool schemas
3. If the response contains tool_calls → execute tools, add results to memory
4. If the response is a plain text finish → return it to the caller
5. Repeat up to ``max_iterations`` times

Usage::

    from eda_agent.agent.planner import Planner

    planner = Planner()
    answer = planner.run("Route the gcd design and tell me the WNS.")
    print(answer)
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from eda_agent.agent.memory import AgentMemory, Message
from eda_agent.agent.tools import TOOL_SCHEMAS, execute_tool
from eda_agent.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are EDA Agent, an expert physical design assistant specialised in
OpenROAD Flow Scripts (ORFS), Cadence Innovus, and Synopsys IC Compiler 2.

Your job is to help the user tune PPA (Power, Performance, Area) metrics
for VLSI designs by:
  1. Running EDA flow stages via the run_eda_stage tool.
  2. Querying timing and congestion results from the database.
  3. Comparing runs and suggesting parameter adjustments.

Always reason step-by-step before calling a tool.
When you have a final answer, summarise the PPA results clearly.
"""


class Planner:
    """ReAct agent that drives EDA tool calls through MiniMax."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self._api_key = api_key or settings.minimax_api_key
        self._model = model or settings.minimax_model
        self._max_iterations = max_iterations or settings.agent_max_iterations
        self._base_url = settings.minimax_base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, user_message: str, memory: AgentMemory | None = None) -> str:
        """Run the ReAct loop and return the final assistant response."""
        mem = memory or AgentMemory()
        mem.add_user(user_message)

        for iteration in range(self._max_iterations):
            logger.debug("ReAct iteration %d", iteration + 1)
            response = self._call_llm(mem)

            choice = response["choices"][0]
            finish_reason = choice.get("finish_reason", "stop")
            message = choice["message"]

            # Persist assistant message
            assistant_text = message.get("content") or ""
            mem.add_assistant(assistant_text)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                # LLM finished without calling more tools → done
                return assistant_text

            # Execute every requested tool call
            for tc in tool_calls:
                tc_id = tc.get("id", str(uuid.uuid4()))
                fn_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"].get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}

                logger.info("Calling tool %s with %s", fn_name, arguments)
                tool_result = execute_tool(fn_name, arguments)
                mem.add_tool_result(fn_name, tool_result, tool_call_id=tc_id)

            if finish_reason == "stop":
                # Finished after tool execution (shouldn't normally happen here)
                break

        # Safety net: return whatever is in the last assistant turn
        return mem.get("last_assistant_text", "Agent reached max iterations.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_llm(self, mem: AgentMemory) -> dict[str, Any]:
        """POST to MiniMax chat completions and return the parsed response."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": mem.get_messages(system_prompt=_SYSTEM_PROMPT),
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
            "max_tokens": settings.minimax_max_tokens,
            "temperature": settings.minimax_temperature,
        }

        # MiniMax requires group_id in the URL when using the v1 API
        group_id = settings.minimax_group_id
        url = (
            f"{self._base_url}/text/chatcompletion_v2"
            if group_id
            else f"{self._base_url}/chat/completions"
        )
        if group_id:
            url += f"?GroupId={group_id}"

        with httpx.Client(timeout=120) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()
