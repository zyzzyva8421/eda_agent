"""Agent chat router – POST /agent/chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner
from eda_agent.agent.tools import execute_tool
import json
from eda_agent.api.auth import get_current_user

router = APIRouter(prefix="/agent", tags=["agent"])

# Per-session memory could be backed by Redis in production;
# for now each request starts a fresh memory context.
# To support multi-turn sessions pass session_id and a server-side store.


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str | None = None


_sessions: dict[str, AgentMemory] = {}


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    _user: dict = Depends(get_current_user),
):
    """Send a message to the EDA agent and get a response.

    If LLM fails, falls back to direct tool execution.
    """
    session_id = req.session_id or f"anon-{_user['username']}"
    if session_id not in _sessions:
        _sessions[session_id] = AgentMemory()

    try:
        planner = Planner()
        reply = planner.run(req.message, memory=_sessions[session_id])
    except Exception as e:
        # Fallback: try to extract parameters and call tool directly
        reply = _fallback_query(req.message)

    return ChatResponse(reply=reply, session_id=session_id)


def _fallback_query(message: str) -> str:
    """Simple keyword-based query fallback when LLM is unavailable."""
    message_lower = message.lower()

    # Extract design name (simple heuristics)
    design = None
    if "design " in message_lower:
        idx = message_lower.find("design ") + 7
        remaining = message[idx:idx + 20]
        design = remaining.split()[0] if remaining else "aes"
    elif "aes" in message_lower:
        design = "aes"
    else:
        return "Could not determine design name. Please include 'design <name>' in your query."

    # Extract stage
    stage = None
    for s in ["synth", "floorplan", "place", "cts", "route", "finish"]:
        if s in message_lower:
            stage = s
            break

    if not stage:
        stage = "finish"  # default

    # Execute query
    try:
        result = json.loads(execute_tool("query_timing", {
            "design_name": design,
            "stage": stage,
            "limit": 5
        }))

        summary = result.get("summary", [])
        paths = result.get("paths", [])

        if not summary:
            return f"No timing data found for design '{design}' stage '{stage}'."

        s = summary[0]
        wns = s.get("wns_ns", "N/A")
        tns = s.get("tns_ns", "N/A")

        reply = f"Timing Summary for design '{design}' (stage: {stage}):\n"
        reply += f"  WNS: {wns} ns\n"
        reply += f"  TNS: {tns} ns\n"

        if paths:
            reply += f"\nWorst Slack Paths:\n"
            for i, p in enumerate(paths[:3], 1):
                sp = p.get("startpoint", "")[:30]
                ep = p.get("endpoint", "")[:30]
                slack = p.get("slack_ns")
                reply += f"  {i}. {sp}... -> {ep}... (slack: {slack} ns)\n"

        return reply

    except Exception as e:
        return f"Error querying database: {e}"


@router.delete("/chat/{session_id}")
def clear_session(session_id: str, _user: dict = Depends(get_current_user)):
    """Clear conversation history for a session."""
    _sessions.pop(session_id, None)
    return {"message": f"Session '{session_id}' cleared."}
