"""
routes/chat_routes.py
----------------------
POST /chat  — patient sends a message, gets AI response.

patient_id comes from the request body (no JWT middleware assumed,
consistent with your existing routes pattern).
Add JWT extraction here later if needed.
"""

from __future__ import annotations
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from models.discharge_history import DischargeHistory
from services.agent.graph import build_agent_graph
from services.agent.chat_history_service import fetch_last_10, save_turn
from services.agent.state import AgentState

_TIMEZONE = ZoneInfo("Asia/Kolkata")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat Agent"])


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    discharge_id: int
    message: str


class ChatResponse(BaseModel):
    discharge_id: int
    user_message: str
    ai_response: str
    intents_detected: list[str]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """
    Main chat endpoint.

    Flow:
      1. Validate patient exists
      2. Fetch last 10 chat history turns
      3. Build + run LangGraph
      4. Save turn to chat_history
      5. Return final_answer
    """
    # 1. Validate discharge
    discharge = db.query(DischargeHistory).filter(
        DischargeHistory.id == req.discharge_id,
    ).first()
    if not discharge:
        raise HTTPException(status_code=404, detail=f"Discharge id={req.discharge_id} not found")

    # 2. Fetch chat history
    history = fetch_last_10(req.discharge_id, db)

    # 3. Build initial state
    now_str = datetime.now(_TIMEZONE).strftime("%A, %d %b %Y, %I:%M %p IST")
    initial_state: AgentState = {
        "discharge_id":     req.discharge_id,
        "user_msg":         req.message.strip(),
        "current_datetime": now_str,
        "chat_history":     history,
        "intents":          [],
        "pending_intents":  [],
        "node_responses":   {},
        "final_answer":     None,
        "call_counts":      {},
        "total_calls":      0,
        "error":            None,
    }

    # 4. Build graph (tools bound to this discharge + session)
    graph = build_agent_graph(req.discharge_id, db)

    # 5. Run graph
    try:
        result: AgentState = graph.invoke(initial_state)
    except Exception as e:
        logger.error("Graph invoke failed for discharge %s: %s", req.discharge_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Agent processing failed. Please try again.")

    # 6. Extract answer
    final_answer = result.get("final_answer") or (
        "I'm sorry, your question appears to be outside my scope. "
        "I can help you with your reports, bills, and medications."
    )
    intents = result.get("intents", [])

    # 7. Save to chat_history (only if we got a real answer)
    try:
        save_turn(req.discharge_id, req.message, final_answer, db)
    except Exception as e:
        logger.warning("Failed to save chat history: %s", e)

    return ChatResponse(
        discharge_id=req.discharge_id,
        user_message=req.message,
        ai_response=final_answer,
        intents_detected=intents,
    )