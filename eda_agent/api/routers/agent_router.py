"""Agent chat router – POST /agent/chat."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from eda_agent.agent.memory import AgentMemory
from eda_agent.agent.planner import Planner
from eda_agent.agent.tools import execute_tool
from eda_agent.api.auth import get_current_user
from eda_agent.db.session import get_db_dependency

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str | None = None


# ── DB-backed session helpers ─────────────────────────────────────────────────


def _load_session(session_id: str, db: Session) -> AgentMemory:
    """Load and deserialise a session from the DB, or return a fresh one."""
    row = db.execute(
        text("SELECT messages FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).mappings().first()
    if row and row["messages"]:
        return AgentMemory.from_messages(row["messages"])
    return AgentMemory()


def _save_session(session_id: str, username: str, memory: AgentMemory, db: Session) -> None:
    """Upsert the serialised session into the DB."""
    messages = memory.get_messages()
    db.execute(
        text(
            """
            INSERT INTO agent_sessions (session_id, username, messages, updated_at)
            VALUES (:sid, :uname, :msgs, now())
            ON CONFLICT (session_id) DO UPDATE
              SET messages = EXCLUDED.messages,
                  updated_at = now()
            """
        ),
        {"sid": session_id, "uname": username, "msgs": json.dumps(messages)},
    )
    db.commit()


# ── Route handlers ────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    """Send a message to the EDA agent and get a response.

    Sessions are persisted in the ``agent_sessions`` database table so they
    survive server restarts and work across multiple instances.
    If the LLM is unavailable a keyword-based fallback is used.
    """
    session_id = req.session_id or f"anon-{_user['username']}"
    memory = _load_session(session_id, db)

    try:
        planner = Planner()
        reply = planner.run(req.message, memory=memory)
    except Exception as exc:
        logger.warning("Planner failed (%s); falling back to keyword query", exc)
        reply = _fallback_query(req.message)

    _save_session(session_id, _user["username"], memory, db)
    return ChatResponse(reply=reply, session_id=session_id)


def _fallback_query(message: str) -> str:
    """Simple keyword-based query fallback when LLM is unavailable."""
    message_lower = message.lower()

    design = None
    if "design " in message_lower:
        idx = message_lower.find("design ") + 7
        remaining = message[idx : idx + 20]
        design = remaining.split()[0] if remaining else "aes"
    elif "aes" in message_lower:
        design = "aes"
    else:
        return "Could not determine design name. Please include 'design <name>' in your query."

    stage = None
    for s in ["synth", "floorplan", "place", "cts", "route", "finish"]:
        if s in message_lower:
            stage = s
            break

    if not stage:
        stage = "finish"

    try:
        result = json.loads(
            execute_tool("query_timing", {"design_name": design, "stage": stage, "limit": 5})
        )

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
            reply += "\nWorst Slack Paths:\n"
            for i, p in enumerate(paths[:3], 1):
                sp = p.get("startpoint", "")[:30]
                ep = p.get("endpoint", "")[:30]
                slack = p.get("slack_ns")
                reply += f"  {i}. {sp}... -> {ep}... (slack: {slack} ns)\n"

        return reply

    except Exception as exc:
        return f"Error querying database: {exc}"


@router.delete("/chat/{session_id}")
def clear_session(
    session_id: str,
    db: Session = Depends(get_db_dependency),
    _user: dict = Depends(get_current_user),
):
    """Clear conversation history for a session."""
    db.execute(
        text("DELETE FROM agent_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    )
    db.commit()
    return {"message": f"Session '{session_id}' cleared."}
