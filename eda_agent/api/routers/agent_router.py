"""Agent chat router – POST /agent/chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner
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
    """Send a message to the EDA agent and get a response."""
    # Reuse or create memory for the session
    session_id = req.session_id or f"anon-{_user['username']}"
    if session_id not in _sessions:
        _sessions[session_id] = AgentMemory()

    planner = Planner()
    reply = planner.run(req.message, memory=_sessions[session_id])
    return ChatResponse(reply=reply, session_id=session_id)


@router.delete("/chat/{session_id}")
def clear_session(session_id: str, _user: dict = Depends(get_current_user)):
    """Clear conversation history for a session."""
    _sessions.pop(session_id, None)
    return {"message": f"Session '{session_id}' cleared."}
