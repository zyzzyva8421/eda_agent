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
import re
import time
import uuid
from typing import Any, Callable

import httpx

from eda_agent.agent.memory import AgentMemory, search_similar_cases
from eda_agent.agent.subagents.contracts import (
    DecisionView,
    HitlGate,
    MultiAgentCycleResult,
)
from eda_agent.agent.tools import TOOL_SCHEMAS, execute_tool
from eda_agent.config import settings
from eda_agent.tracing import is_tracing_enabled, trace_chat

logger = logging.getLogger(__name__)

# Matches a single <tool_call>...</tool_call> block in model text output.
# Used by the prompt-mode tool calling path.
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)

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

    _CASE_TEXT_MAX_CHARS = 400
    _CASE_ACTIONS_MAX_ITEMS = 4
    _CASE_METRICS_MAX_CHARS = 300

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
        self._request_timeout = httpx.Timeout(settings.minimax_request_timeout_sec)
        self._stream_timeout = httpx.Timeout(settings.minimax_stream_timeout_sec)
        self._input_max_tokens = settings.minimax_input_max_tokens
        self._timeout_retry_input_max_tokens = settings.minimax_timeout_retry_input_max_tokens

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        user_message: str,
        memory: AgentMemory | None = None,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        stream: bool = False,
    ) -> str:
        """Run the ReAct loop and return the final assistant response.

        Parameters
        ----------
        user_message:
            The user's input for this turn.
        memory:
            Conversation memory to extend.  A fresh :class:`AgentMemory`
            is used when omitted.
        on_event:
            Optional progress callback ``fn(kind, payload)``.  Emitted
            kinds: ``iteration_start``, ``tool_call``, ``tool_result``,
            ``async_submission``, ``trace``.  Exceptions raised by the
            callback are swallowed so a bad listener cannot break the
            planner.
        stream:
            When True and the final assistant turn has no tool calls,
            stream the LLM response via SSE and emit ``token`` events
            through *on_event*.  Falls back to the non-streaming path on
            any error so the agent always produces a final reply.
        """
        # NOTE: AgentMemory defines __len__, so an empty memory object is
        # falsy. We must check explicitly for None, otherwise we'd silently
        # replace the caller-provided memory and lose session history.
        mem = memory if memory is not None else AgentMemory()

        def _emit(kind: str, payload: dict[str, Any]) -> None:
            if on_event is None:
                return
            try:
                on_event(kind, payload)
            except Exception:  # noqa: BLE001 -- listeners must never crash the planner
                logger.debug("on_event listener raised", exc_info=True)

        # Retrieve similar historical cases once per *user turn* (topic may
        # change between turns) with a small LRU cache keyed by the query
        # text.  Results are stored in the volatile ``_similar_cases``
        # slot, which is excluded from session persistence.
        self._refresh_similar_cases(mem, user_message)

        mem.add_user(user_message)

        for iteration in range(self._max_iterations):
            logger.debug("ReAct iteration %d", iteration + 1)
            _emit("iteration_start", {"iteration": iteration + 1})
            response = self._call_llm(mem, stream=stream, on_event=_emit)

            # Surface tracing metadata (LangSmith) for observability.
            tracing_meta = response.get("_tracing") if isinstance(response, dict) else None
            if tracing_meta:
                _emit("trace", tracing_meta)

            # Handle empty or None response
            if not response or not response.get("choices"):
                return self._last_assistant_text(mem) or (
                    "Sorry, I couldn't process that request."
                )

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
                _emit("tool_call", {"name": fn_name, "arguments": arguments})

                _t0 = time.monotonic()
                tool_ok = True
                try:
                    tool_result = execute_tool(fn_name, arguments)
                except Exception as exc:  # noqa: BLE001 -- propagated after emit
                    tool_ok = False
                    _emit(
                        "tool_result",
                        {
                            "name": fn_name,
                            "ok": False,
                            "preview": f"{type(exc).__name__}: {exc}",
                            "duration": time.monotonic() - _t0,
                        },
                    )
                    raise
                _emit(
                    "tool_result",
                    {
                        "name": fn_name,
                        "ok": tool_ok,
                        "preview": tool_result,
                        "duration": time.monotonic() - _t0,
                    },
                )
                mem.add_tool_result(fn_name, tool_result, tool_call_id=tc_id)

                # Async flow/stage submissions should return immediately with a
                # job id so the CLI stays interactive. If we already have that,
                # stop the ReAct loop early instead of consuming max iterations.
                if fn_name in ("submit_job", "run_eda_flow"):
                    maybe_job = self._extract_job_submission(tool_result)
                    if maybe_job is not None:
                        async_submission_job = maybe_job

                # Extract and store design context from structured tool arguments
                self._extract_and_store_context(fn_name, arguments, tool_result, mem)

            if async_submission_job is not None:
                _emit("async_submission", async_submission_job)
                return self._format_async_submission_reply(async_submission_job)

            if finish_reason == "stop":
                break

        # Safety net: return whatever is in the last assistant turn
        return self._last_assistant_text(mem) or "Agent reached max iterations."

    @staticmethod
    def _last_assistant_text(mem: AgentMemory) -> str:
        """Return the most recent assistant ``content`` from history, if any."""
        for m in reversed(mem.get_messages()):
            if m.get("role") == "assistant" and m.get("content"):
                return str(m["content"])
        return ""

    def run_multi_agent_cycle(
        self,
        objective: str,
        *,
        session_id: int | None = None,
        run_id: int | None = None,
        constraints: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        agents: list[str] | None = None,
    ) -> MultiAgentCycleResult:
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
    def _build_decision_view(merged: dict[str, Any]) -> DecisionView:
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
    def _apply_hitl_gate(merged: dict[str, Any]) -> HitlGate:
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

    def _call_llm(
        self,
        mem: AgentMemory,
        *,
        stream: bool = False,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """POST to MiniMax chat completions and return the parsed response.

        When *stream* is True, an SSE request is issued and ``token``
        events are emitted via *on_event* as content deltas arrive.  The
        method then re-assembles a standard non-streaming response dict
        so the rest of the ReAct loop is oblivious to the transport.
        Any error during streaming falls back to the non-streaming path.
        """
        prompt_mode = settings.llm_tool_calling_mode == "prompt"
        headers = {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
        }

        group_id = settings.minimax_group_id
        url = (
            f"{self._base_url}/text/chatcompletion_v2"
            if group_id
            else f"{self._base_url}/chat/completions"
        )
        if group_id:
            url += f"?GroupId={group_id}"

        transport = httpx.HTTPTransport()
        payload = self._build_payload(
            mem,
            prompt_mode=prompt_mode,
            include_similar_cases=True,
            max_input_tokens=self._input_max_tokens,
        )
        if stream:
            payload["stream"] = True
            try:
                raw_response = self._call_llm_stream(
                    url, headers, payload, transport, on_event=on_event
                )
            except Exception:  # noqa: BLE001 -- streaming is best-effort
                logger.warning(
                    "Streaming LLM call failed; falling back to non-stream",
                    exc_info=True,
                )
                payload.pop("stream", None)
                raw_response = self._post_chat_completion(
                    url,
                    headers,
                    payload,
                    transport,
                    mem=mem,
                    prompt_mode=prompt_mode,
                )
        else:
            raw_response = self._post_chat_completion(
                url,
                headers,
                payload,
                transport,
                mem=mem,
                prompt_mode=prompt_mode,
            )

        if prompt_mode:
            raw_response = self._normalize_prompt_mode_response(raw_response)

        if is_tracing_enabled():
            raw_response = trace_chat(
                messages=payload["messages"],
                response=raw_response,
                model=self._model,
            )

        return raw_response

    def _build_payload(
        self,
        mem: AgentMemory,
        *,
        prompt_mode: bool,
        include_similar_cases: bool,
        max_input_tokens: int | None,
    ) -> dict[str, Any]:
        full_system_prompt = self._build_system_prompt(
            mem, include_similar_cases=include_similar_cases
        )
        if prompt_mode:
            full_system_prompt += self._tools_to_system_appendix(TOOL_SCHEMAS)

        token_budget = (
            max_input_tokens if max_input_tokens and max_input_tokens > 0 else None
        )
        messages = mem.get_messages(
            system_prompt=full_system_prompt,
            max_tokens=token_budget,
        )
        if prompt_mode:
            messages = self._messages_for_prompt_mode(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": settings.minimax_max_tokens,
            "temperature": settings.minimax_temperature,
        }
        if not prompt_mode:
            payload["tools"] = TOOL_SCHEMAS
            payload["tool_choice"] = "auto"
        return payload

    def _build_system_prompt(
        self,
        mem: AgentMemory,
        *,
        include_similar_cases: bool,
    ) -> str:
        context_prompt = ""
        context = mem.extract_design_context()
        if context:
            context_prompt = "\n\n## Current Design Context (USE THIS)\n"
            for k, v in context.items():
                context_prompt += f"- {k}: {v}\n"

        cases_prompt = ""
        if include_similar_cases:
            similar_cases: list[dict[str, Any]] = mem.get("_similar_cases") or []
            cases_prompt = self._format_similar_cases_prompt(similar_cases)

        return _SYSTEM_PROMPT + context_prompt + cases_prompt

    def _post_chat_completion(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        transport: httpx.HTTPTransport,
        *,
        mem: AgentMemory,
        prompt_mode: bool,
    ) -> dict[str, Any]:
        try:
            return self._send_json_request(
                url,
                headers,
                payload,
                transport,
                timeout=self._request_timeout,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "LLM request timed out; retrying with reduced context",
                exc_info=True,
            )
            retry_budget = self._timeout_retry_input_max_tokens
            if retry_budget <= 0:
                if self._input_max_tokens > 0:
                    retry_budget = max(1, self._input_max_tokens // 2)
                else:
                    retry_budget = max(1, settings.minimax_max_tokens // 2)
            has_similar_cases = bool(mem.get("_similar_cases"))
            reduces_context = has_similar_cases or (
                self._input_max_tokens > 0 and retry_budget < self._input_max_tokens
            )
            if retry_budget <= 0 or not reduces_context:
                raise TimeoutError("LLM request timed out") from exc
            retry_payload = self._build_payload(
                mem,
                prompt_mode=prompt_mode,
                include_similar_cases=False,
                max_input_tokens=retry_budget,
            )
            try:
                return self._send_json_request(
                    url,
                    headers,
                    retry_payload,
                    transport,
                    timeout=self._request_timeout,
                )
            except httpx.TimeoutException as retry_exc:
                raise TimeoutError("LLM request timed out") from retry_exc

    @staticmethod
    def _send_json_request(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        transport: httpx.HTTPTransport,
        *,
        timeout: httpx.Timeout,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    @classmethod
    def _format_similar_cases_prompt(
        cls, similar_cases: list[dict[str, Any]]
    ) -> str:
        if not similar_cases:
            return ""

        cases_prompt = "\n\n## Similar Historical Cases (for reference)\n"
        for i, case in enumerate(similar_cases, 1):
            actions = case.get("actions") or []
            action_text = "; ".join(
                cls._truncate_text(action, cls._CASE_TEXT_MAX_CHARS)
                for action in actions[: cls._CASE_ACTIONS_MAX_ITEMS]
            )
            cases_prompt += (
                f"\n### Case {i} (design: {case.get('design_name', 'unknown')})\n"
                f"**Symptoms**: "
                f"{cls._truncate_text(case.get('symptoms', ''), cls._CASE_TEXT_MAX_CHARS)}\n"
                f"**Root cause**: "
                f"{cls._truncate_text(case.get('root_cause', ''), cls._CASE_TEXT_MAX_CHARS)}\n"
                f"**Actions taken**: {action_text}\n"
            )
            metrics = case.get("result_metrics") or {}
            if metrics:
                metrics_text = cls._truncate_text(
                    json.dumps(metrics, ensure_ascii=False),
                    cls._CASE_METRICS_MAX_CHARS,
                )
                cases_prompt += f"**Result metrics**: {metrics_text}\n"
        return cases_prompt

    @staticmethod
    def _truncate_text(value: Any, limit: int) -> str:
        text = str(value or "")
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        return text[: max(limit - 1, 0)] + "…"

    def _call_llm_stream(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        transport: httpx.HTTPTransport,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Issue an SSE chat completion and re-assemble a regular response.

        Follows the OpenAI streaming format used by MiniMax's v2 endpoint:
        the server emits ``data: {...}`` lines (one JSON object per line),
        terminated by ``data: [DONE]``.  Each chunk contains a
        ``choices[0].delta`` with optional ``content`` and ``tool_calls``
        fragments.  We accumulate these into a single ``message`` dict.
        """
        accumulated_content: list[str] = []
        accumulated_reasoning: list[str] = []
        # tool_calls are accumulated by index (OpenAI streaming spec).
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        model_name = self._model

        with httpx.Client(timeout=self._stream_timeout, transport=transport) as client:
            with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    if isinstance(raw_line, str):
                        line = raw_line
                    else:
                        line = raw_line.decode("utf-8", "replace")
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    model_name = chunk.get("model", model_name)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}
                    if "content" in delta and delta["content"]:
                        accumulated_content.append(delta["content"])
                        if on_event is not None:
                            try:
                                on_event("token", {"content": delta["content"]})
                            except Exception:  # noqa: BLE001
                                pass
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        accumulated_reasoning.append(delta["reasoning_content"])
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tool_calls_by_index.setdefault(
                            idx,
                            {
                                "id": tc.get("id"),
                                "type": tc.get("type", "function"),
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(accumulated_content),
        }
        if accumulated_reasoning:
            message["reasoning_content"] = "".join(accumulated_reasoning)
        if tool_calls_by_index:
            ordered = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]
            # Ensure every tool call has an id.
            for tc in ordered:
                if not tc.get("id"):
                    tc["id"] = str(uuid.uuid4())
            message["tool_calls"] = ordered

        return {
            "model": model_name,
            "choices": [{"finish_reason": finish_reason, "message": message}],
        }

    # ------------------------------------------------------------------
    # Prompt-mode tool calling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tools_to_system_appendix(tools: list) -> str:
        """Return a system-prompt appendix describing available tools.

        Used by the ``prompt`` tool-calling mode to inject tool schemas as
        plain text instead of relying on the OpenAI ``tools`` API field.
        The model is instructed to respond with ``<tool_call>`` blocks so
        that :meth:`_normalize_prompt_mode_response` can extract them.
        """
        compact: list = []
        for entry in tools:
            fn = entry.get("function") or entry
            compact.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                }
            )
        tools_json = json.dumps(compact, ensure_ascii=False)
        return (
            "\n\n## Available Tools\n\n"
            "You can call the following tools to help the user.  "
            "When you need to invoke a tool, include a `<tool_call>` block in "
            "your response (you may also include brief explanatory text):\n\n"
            "<tool_call>\n"
            '{"name": "TOOL_NAME", "arguments": {"arg": "value"}}\n'
            "</tool_call>\n\n"
            "After receiving a tool result you may call another tool or give "
            "your final answer.\n\n"
            f"### Tool schemas (JSON)\n```json\n{tools_json}\n```"
        )

    @staticmethod
    def _messages_for_prompt_mode(messages: list) -> list:
        """Rewrite the message list to be compatible with a plain chat template.

        A basic ``--chat-template`` (e.g. the one used for local Gemma 4
        deployments) only understands ``system`` / ``user`` / ``assistant``
        roles and accesses ``message['content']`` directly.  It cannot
        render ``role=tool`` messages or ``assistant`` messages whose
        ``content`` is empty (tool-call turns).

        This method converts:

        * ``assistant`` turns that carry ``tool_calls`` (and often empty
          ``content``) → serialised ``<tool_call>`` text so the model sees
          what it previously decided to call.
        * ``tool`` result turns → ``user`` turns prefixed with
          ``[Tool result for <name>]``.
        """
        result: list = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""

            if role in ("system", "user"):
                result.append({"role": role, "content": content})

            elif role == "assistant":
                tool_calls: list = msg.get("tool_calls") or []
                if tool_calls and not content:
                    parts: list = []
                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        name = fn.get("name", "unknown")
                        args_raw = fn.get("arguments", "{}")
                        try:
                            args_pretty = json.dumps(
                                json.loads(args_raw), ensure_ascii=False
                            )
                        except Exception:
                            args_pretty = args_raw
                        parts.append(
                            f'<tool_call>\n{{"name": "{name}", "arguments": {args_pretty}}}\n</tool_call>'
                        )
                    content = "\n".join(parts)
                result.append({"role": "assistant", "content": content})

            elif role == "tool":
                tool_name = msg.get("name", "unknown_tool")
                result.append(
                    {
                        "role": "user",
                        "content": f"[Tool result for {tool_name}]\n{content}",
                    }
                )
        return result

    @staticmethod
    def _parse_tool_calls_from_text(text: str) -> list:
        """Extract ``<tool_call>`` blocks from a model text response.

        Returns a list of OpenAI-compatible ``tool_calls`` dicts so the
        main ReAct loop can process them without special-casing the
        prompt-mode path.

        Each ``<tool_call>`` block must contain a JSON object with at
        least a ``"name"`` key and an optional ``"arguments"`` dict.
        Malformed blocks are skipped with a debug-level warning.
        """
        calls: list = []
        for match in _TOOL_CALL_RE.finditer(text):
            raw = match.group(1).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug(
                    "prompt-mode: ignoring malformed tool_call block: %r", raw
                )
                continue
            if not isinstance(data, dict) or not data.get("name"):
                logger.debug(
                    "prompt-mode: tool_call block missing name: %r", data
                )
                continue
            args = data.get("arguments", {})
            calls.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "function",
                    "function": {
                        "name": data["name"],
                        "arguments": (
                            json.dumps(args, ensure_ascii=False)
                            if isinstance(args, dict)
                            else str(args)
                        ),
                    },
                }
            )
        return calls

    def _normalize_prompt_mode_response(self, raw_response: dict) -> dict:
        """Inject parsed tool calls into a prompt-mode LLM response.

        When the model returns a text response that contains one or more
        ``<tool_call>`` blocks, this method:

        1. Strips the blocks from the visible ``content``.
        2. Injects the parsed tool calls into ``message["tool_calls"]``.
        3. Sets ``finish_reason`` to ``"tool_calls"`` so the ReAct loop
           proceeds to tool execution unchanged.
        """
        choices = raw_response.get("choices") or []
        if not choices:
            return raw_response
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""

        parsed = self._parse_tool_calls_from_text(content)
        if not parsed:
            return raw_response  # no tool calls; return as-is

        # Strip the <tool_call> blocks from the displayed content.
        clean_content = _TOOL_CALL_RE.sub("", content).strip()

        new_message = dict(message)
        new_message["content"] = clean_content
        new_message["tool_calls"] = parsed

        new_choice = dict(choice)
        new_choice["message"] = new_message
        new_choice["finish_reason"] = "tool_calls"

        new_response = dict(raw_response)
        new_response["choices"] = [new_choice] + choices[1:]
        return new_response

    def _extract_and_store_context(
        self,
        fn_name: str,
        arguments: dict[str, Any],
        tool_result: str,
        mem: AgentMemory,
    ) -> None:
        """Update the durable session context from any tool that exposes it.

        Replaces the previous hard-coded whitelist; we now look at every
        tool call (arguments + result) for keys in
        :data:`eda_agent.agent.memory.CONTEXT_KEYS` so that
        ``query_timing`` / ``submit_job`` / ``run_ppa_tuning`` etc. also
        refresh ``design_name`` / ``pdk`` / ``run_id``.
        """
        del fn_name  # parameter kept for API stability
        mem.update_context_from_tool(arguments, tool_result)

    # ------------------------------------------------------------------
    # Case retrieval helpers
    # ------------------------------------------------------------------

    _CASE_CACHE_MAX = 8

    def _refresh_similar_cases(self, mem: AgentMemory, user_message: str) -> None:
        """Refresh ``_similar_cases`` for the current user turn.

        Caches up to :attr:`_CASE_CACHE_MAX` recent queries in the
        volatile scratchpad so a back-and-forth conversation about the
        same topic does not hammer the DB.
        """
        query = (user_message or "").strip()
        if not query:
            mem.set("_similar_cases", [])
            return

        cache: dict[str, list[dict[str, Any]]] = mem.get("_cases_cache") or {}
        if query in cache:
            mem.set("_similar_cases", cache[query])
            return

        try:
            similar = search_similar_cases(query, limit=3) or []
        except Exception:
            logger.debug("similar-case lookup failed", exc_info=True)
            similar = []

        cache[query] = similar
        # Keep the cache bounded so a long session can't bloat memory.
        if len(cache) > self._CASE_CACHE_MAX:
            # drop oldest insertion
            first_key = next(iter(cache))
            cache.pop(first_key, None)
        mem.set("_cases_cache", cache)
        mem.set("_similar_cases", similar)
