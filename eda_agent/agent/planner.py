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

from eda_agent.agent.memory import AgentMemory, Message, search_similar_cases
from eda_agent.agent.tools import TOOL_SCHEMAS, execute_tool
from eda_agent.config import settings
from eda_agent.tracing import is_tracing_enabled, trace_chat

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

## Innovus Configuration - IMPORTANT
For Innovus backend, the following parameters can be auto-filled from system settings:
- design_config: automatically set to INNOVUS_REMOTE_WORKDIR
- pdk: automatically set to "tsmc18"
- backend: automatically inferred from stage name (place/cts/route/floorplan/powerplan/prects/postcts/postroute/signoff → innovus)

When calling run_eda_stage for Innovus (place/cts/route etc), you can omit:
- design_config (auto-filled from settings)
- pdk (default "tsmc18")
- backend (auto-inferred from stage name)

Example: run_eda_stage(stage="place", design_name="DTMF_CHIP") # backend/pdk auto-filled

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

        # Inject similar historical cases into the scratchpad so _call_llm can
        # include them in the system prompt.  We do this once per session (when
        # the first user message arrives) using a lightweight DB query; failures
        # are silently ignored so offline/test environments still work.
        if not mem.get("_cases_loaded"):
            similar = search_similar_cases(user_message, limit=3)
            if similar:
                mem.set("_similar_cases", similar)
            mem.set("_cases_loaded", True)

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

                # Extract and store design context from structured tool arguments
                self._extract_and_store_context(fn_name, arguments, mem)

            if async_submission_job is not None:
                return self._format_async_submission_reply(async_submission_job)

            if finish_reason == "stop":
                break

        # Safety net: return whatever is in the last assistant turn
        return mem.get("last_assistant_text", "Agent reached max iterations.")

    def run_multi_agent_cycle(
        self,
        objective: str,
        *,
        session_id: int | None = None,
        run_id: int | None = None,
        constraints: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        agents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a minimal multi-agent orchestration cycle.

        This is an M1 skeleton entry that does not alter the existing ReAct
        chat loop. It can be called by future tools/endpoints to orchestrate
        specialized sub-agents in a consistent envelope format.
        """
        task = {
            "task_id": str(uuid.uuid4()),
            "objective": objective,
            "session_id": session_id,
            "run_id": run_id,
            "constraints": constraints or {},
            "inputs": inputs or {},
            "agents": agents or ["pnr", "sta", "signoff", "experiment"],
        }
        envelopes = self._dispatch_subagents(task)
        merged = self._merge_agent_outputs(envelopes)
        gate = self._apply_hitl_gate(merged)
        status_counts = self._status_counts(envelopes)
        decision_view = self._build_decision_view(merged)
        return {
            "contract_version": "v1",
            "task_id": task["task_id"],
            "session_id": session_id,
            "run_id": run_id,
            "objective": objective,
            "agents": [e["agent"] for e in envelopes],
            "envelopes": envelopes,
            "merged": merged,
            "status_summary": {
                "total": len(envelopes),
                "ok": status_counts["ok"],
                "needs_approval": status_counts["needs_approval"],
                "error": status_counts["error"],
                "has_error": merged.get("has_error", False),
            },
            "decision_view": decision_view,
            "gate": gate,
        }

    @staticmethod
    def _status_counts(envelopes: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"ok": 0, "needs_approval": 0, "error": 0}
        for env in envelopes:
            status = str(env.get("status") or "error")
            if status not in counts:
                counts["error"] += 1
                continue
            counts[status] += 1
        return counts

    @staticmethod
    def _build_decision_view(merged: dict[str, Any]) -> dict[str, Any]:
        by_agent = merged.get("by_agent") or {}
        pnr_out = ((by_agent.get("pnr") or {}).get("outputs") or {})
        sta_out = ((by_agent.get("sta") or {}).get("outputs") or {})
        signoff_out = ((by_agent.get("signoff") or {}).get("outputs") or {})
        experiment_out = ((by_agent.get("experiment") or {}).get("outputs") or {})

        return {
            "candidate_experiments": pnr_out.get("candidate_experiments", []),
            "constraint_warnings": sta_out.get("constraint_warnings", []),
            "signoff_ready": bool(signoff_out.get("signoff_ready", False)),
            "next_action": experiment_out.get("next_action", "propose_experiment"),
            "risk_level": experiment_out.get("risk_level", "low"),
            "requires_approval": bool(experiment_out.get("requires_approval", False)),
        }

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

    @staticmethod
    def _dispatch_subagents(task: dict[str, Any]) -> list[dict[str, Any]]:
        """Dispatch a task to selected specialized sub-agents.

        Returns a list of serializable envelope dicts.
        """
        from eda_agent.agent.subagents import (
            AgentEnvelope,
            ExperimentAgent,
            PnRAgent,
            STAAgent,
            SignoffAgent,
        )

        registry = {
            "pnr": PnRAgent(),
            "sta": STAAgent(),
            "signoff": SignoffAgent(),
            "experiment": ExperimentAgent(),
        }

        selected = task.get("agents") or ["pnr", "sta", "signoff", "experiment"]
        envelopes: list[dict[str, Any]] = []

        for name in selected:
            agent = registry.get(name)
            if agent is None:
                envelopes.append(
                    AgentEnvelope.error_result(
                        task_id=task["task_id"],
                        agent=name,
                        objective=str(task.get("objective", "")),
                        session_id=task.get("session_id"),
                        run_id=task.get("run_id"),
                        constraints=task.get("constraints") or {},
                        inputs=task.get("inputs") or {},
                        error=f"Unknown sub-agent '{name}'",
                    ).__dict__
                )
                continue

            envelope = AgentEnvelope(
                task_id=task["task_id"],
                agent=name,
                session_id=task.get("session_id"),
                run_id=task.get("run_id"),
                objective=str(task.get("objective", "")),
                constraints=task.get("constraints") or {},
                inputs=task.get("inputs") or {},
            )

            try:
                result = agent.run(envelope)
                envelopes.append(result.__dict__)
            except Exception as exc:
                logger.warning("Sub-agent %s failed", name, exc_info=True)
                envelopes.append(
                    AgentEnvelope.error_result(
                        task_id=task["task_id"],
                        agent=name,
                        objective=str(task.get("objective", "")),
                        session_id=task.get("session_id"),
                        run_id=task.get("run_id"),
                        constraints=task.get("constraints") or {},
                        inputs=task.get("inputs") or {},
                        error=str(exc),
                    ).__dict__
                )

        return envelopes

    @staticmethod
    def _merge_agent_outputs(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge sub-agent outputs into a single structure for arbitration."""
        by_agent: dict[str, Any] = {}
        has_error = False
        for env in envelopes:
            agent = str(env.get("agent", "unknown"))
            by_agent[agent] = {
                "status": env.get("status", "error"),
                "outputs": env.get("outputs") or {},
                "error": env.get("error", ""),
            }
            if env.get("status") == "error":
                has_error = True
        return {
            "by_agent": by_agent,
            "has_error": has_error,
        }

    @staticmethod
    def _apply_hitl_gate(merged: dict[str, Any]) -> dict[str, Any]:
        """Apply minimal human-in-the-loop gate based on merged outputs."""
        exp = (merged.get("by_agent") or {}).get("experiment") or {}
        exp_out = exp.get("outputs") or {}
        risk_level = str(exp_out.get("risk_level", "low"))
        requires_approval = bool(exp_out.get("requires_approval", False))
        blocked = requires_approval or risk_level == "high"
        return {
            "blocked": blocked,
            "status": "needs_approval" if blocked else "auto_execute",
            "reason": "high risk experiment" if blocked else "",
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_llm(self, mem: AgentMemory) -> dict[str, Any]:
        """POST to MiniMax chat completions and return the parsed response."""

        # Inject design context into system prompt if available
        context = mem.extract_design_context()
        context_prompt = ""
        if context:
            context_prompt = "\n\n## Current Design Context (USE THIS)\n"
            for k, v in context.items():
                context_prompt += f"- {k}: {v}\n"

        # Inject similar historical cases if available
        cases_prompt = ""
        similar_cases: list[dict] = mem.get("_similar_cases") or []
        if similar_cases:
            cases_prompt = "\n\n## Similar Historical Cases (for reference)\n"
            for i, case in enumerate(similar_cases, 1):
                cases_prompt += (
                    f"\n### Case {i} (design: {case.get('design_name', 'unknown')})\n"
                    f"**Symptoms**: {case.get('symptoms', '')}\n"
                    f"**Root cause**: {case.get('root_cause', '')}\n"
                    f"**Actions taken**: {'; '.join(case.get('actions', []))}\n"
                )
                metrics = case.get("result_metrics") or {}
                if metrics:
                    cases_prompt += f"**Result metrics**: {metrics}\n"

        # Build full system prompt
        full_system_prompt = _SYSTEM_PROMPT + context_prompt + cases_prompt

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
            raw_response = resp.json()

        # Trace the LLM call if enabled
        if is_tracing_enabled():
            raw_response = trace_chat(
                messages=payload["messages"],
                response=raw_response,
                model=self._model,
            )

        return raw_response

    def _extract_and_store_context(
        self,
        fn_name: str,
        arguments: dict[str, Any],
        mem: AgentMemory,
    ) -> None:
        """Extract design context from structured tool arguments → scratchpad.

        Uses only the *arguments* dict (already a structured Python dict from
        the LLM's function call).  No JSON parsing of serialised tool results.
        """
        if fn_name not in ("run_eda_stage", "run_eda_flow"):
            return

        for arg_key, scratch_key in (
            ("design_name", "design_name"),
            ("pdk", "pdk"),
            ("design_config", "config_path"),
        ):
            if arg_key in arguments:
                mem.set(scratch_key, arguments[arg_key])
