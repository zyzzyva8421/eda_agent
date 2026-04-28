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
    1. Running EDA flow stages via tools.
  2. Querying timing and congestion results from the database.
  3. Comparing runs and suggesting parameter adjustments.

## Execution Policy - IMPORTANT
- For multi-stage or long-running requests (e.g. "run from synth to finish", "run full flow"),
    prefer asynchronous submission via run_eda_flow (returns job_id) or submit_job with run_mode="flow".
- Avoid long synchronous tool executions that block CLI interaction.
- Use job_status/job_logs to monitor progress after submission.

## Context Tracking - IMPORTANT
The system automatically tracks design context from your tool calls. After 
running a design, the following context is stored:
- design_name: the name of the design (e.g., "aes", "gcd")  
- pdk: the PDK being used (e.g., "sky130hd")
- config_path: the path to the design config file

When the user asks about "the final stage" or "the worst path" or any design-
related question, you MUST use query_timing tool WITHOUT asking for clarification.
The tool will automatically get the latest run for the current design.

IMPORTANT: Do NOT ask the user for design name or PDK. Use the stored context.
If you just ran "run design aes...", the design_name is "aes" and pdk is "sky130hd".

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

            # Handle empty or None response
            if not response or not response.get("choices"):
                return mem.get("last_assistant_text", "Sorry, I couldn't process that request.")

            choice = response["choices"][0]
            finish_reason = choice.get("finish_reason", "stop")
            message = choice.get("message", {})

            # Persist assistant message
            assistant_text = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            
            # Include reasoning_content if content is empty (MiniMax specific)
            if not assistant_text and message.get("reasoning_content"):
                assistant_text = message.get("reasoning_content", "")
            
            # Add assistant message with tool_calls so MiniMax can match tool results
            if tool_calls:
                mem.add_assistant(assistant_text, tool_calls=tool_calls)
            elif assistant_text:
                mem.add_assistant(assistant_text)

            if not tool_calls:
                # LLM finished without calling more tools → done
                return assistant_text or "Tool executed. Here's your result:"

            # Execute every requested tool call
            async_submission_job: dict[str, Any] | None = None
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

                # Async flow/stage submissions should return immediately with a
                # job id so the CLI stays interactive. If we already have that,
                # stop the ReAct loop early instead of consuming max iterations.
                if fn_name in ("submit_job", "run_eda_flow"):
                    maybe_job = self._extract_job_submission(tool_result)
                    if maybe_job is not None:
                        async_submission_job = maybe_job

                # Extract and store design context from tool results
                self._extract_and_store_context(fn_name, arguments, tool_result, mem)

            if async_submission_job is not None:
                return self._format_async_submission_reply(async_submission_job)

            if finish_reason == "stop":
                break

        # Safety net: return whatever is in the last assistant turn
        return mem.get("last_assistant_text", "Agent reached max iterations.")

    @staticmethod
    def _extract_job_submission(tool_result: str) -> dict[str, Any] | None:
        """Return parsed async job payload when tool_result contains a job_id."""
        try:
            payload = json.loads(tool_result)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("job_id"):
            return payload
        return None

    @staticmethod
    def _format_async_submission_reply(job_payload: dict[str, Any]) -> str:
        """Human-friendly confirmation for async job submissions."""
        job_id = job_payload.get("job_id")
        status = job_payload.get("status", "pending")
        message = job_payload.get("message") or "Job submitted successfully."
        return (
            f"任务已异步提交。\\n"
            f"- job_id: {job_id}\\n"
            f"- status: {status}\\n"
            f"- next: 可用 job_status 查询进度，job_logs 查看日志。\\n"
            f"- note: {message}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_llm(self, mem: AgentMemory) -> dict[str, Any]:
        """POST to MiniMax chat completions and return the parsed response."""
        
        # Inject design context into system prompt if available
        context = mem.extract_design_context()
        context_prompt = ""
        if context:
            context_prompt = f"\n\n## Current Design Context (USE THIS)\n"
            for k, v in context.items():
                context_prompt += f"- {k}: {v}\n"
        
        # Build full system prompt with context
        full_system_prompt = _SYSTEM_PROMPT + context_prompt
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": mem.get_messages(system_prompt=full_system_prompt),
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

        # Create client without proxy settings
        transport = httpx.HTTPTransport()
        with httpx.Client(timeout=120, transport=transport) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _extract_and_store_context(
        self,
        fn_name: str,
        arguments: dict[str, Any],
        tool_result: str,
        mem: AgentMemory,
    ) -> None:
        """Extract design context from tool calls and store in memory scratchpad."""
        if fn_name not in ("run_eda_stage", "run_eda_flow"):
            return
        
        # Extract from arguments (the user's request)
        if "design_name" in arguments:
            mem.set("design_name", arguments["design_name"])
        if "pdk" in arguments:
            mem.set("pdk", arguments["pdk"])
        if "design_config" in arguments:
            mem.set("config_path", arguments["design_config"])
        
        # Also try to extract from tool result
        try:
            import json
            result = json.loads(tool_result)
            if isinstance(result, dict):
                # Use result values if not already set
                if not mem.get("design_name") and "design_name" in result:
                    mem.set("design_name", result["design_name"])
                if not mem.get("pdk") and "pdk" in result:
                    mem.set("pdk", result["pdk"])
        except Exception:
            pass
