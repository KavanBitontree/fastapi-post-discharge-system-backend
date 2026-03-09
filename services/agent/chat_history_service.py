"""
services/agent/chat_history_service.py
----------------------------------------
Fetch and save chat_history rows.
"""

from __future__ import annotations
from sqlalchemy.orm import Session
from models.chat_history import ChatHistory


def fetch_last_10(patient_id: int, db: Session) -> list[dict]:
    """
    Fetch the last 10 conversation turns for a patient,
    returned as [{"role": "user"|"assistant", "content": str}, ...].
    Ordered oldest → newest so LLMs read them chronologically.
    """
    rows = (
        db.query(ChatHistory)
        .filter(ChatHistory.patient_id == patient_id)
        .order_by(ChatHistory.timestamp.desc())
        .limit(10)
        .all()
    )
    rows.reverse()  # oldest first

    history = []
    for row in rows:
        history.append({"role": "user",      "content": row.user_msg})
        history.append({"role": "assistant", "content": row.ai_msg})
    return history


def save_turn(patient_id: int, user_msg: str, ai_msg: str, db: Session) -> None:
    """Persist a completed conversation turn."""
    entry = ChatHistory(
        patient_id=patient_id,
        user_msg=user_msg,
        ai_msg=ai_msg,
    )
    db.add(entry)
    db.commit()