"""
services/agent/state.py
------------------------
Shared state that flows through every node in the LangGraph.

TypedDict fields:
  patient_id      — resolved from request, never changes
  user_msg        — original message from patient
  chat_history    — last 10 turns fetched once at graph entry
  intents         — list decided by Supervisor: ["reports"], ["bills","medicine"], etc.
  pending_intents — intents not yet processed (popped as each node runs)
  node_responses  — dict collecting each node's answer  {"reports": "...", ...}
  final_answer    — synthesized answer written by Supervisor before END
  call_counts     — tracks LLM calls per node for loop guard
  total_calls     — global LLM call counter
  error           — set if something goes wrong, triggers graceful END
"""

from __future__ import annotations
from typing import TypedDict, Optional


class AgentState(TypedDict):
    patient_id:       int
    user_msg:         str
    current_datetime: str                # ISO-like string: "Monday, 09 Mar 2026, 02:15 PM IST"
    chat_history:     list[dict]         # [{"role": "user"|"assistant", "content": str}]
    intents:          list[str]          # e.g. ["reports", "medicine"]
    pending_intents:  list[str]          # copy of intents, shrinks as nodes finish
    node_responses:   dict[str, str]     # {"reports": "answer...", "bills": "answer..."}
    final_answer:     Optional[str]
    call_counts:      dict[str, int]     # {"supervisor": 2, "reports": 1, ...}
    total_calls:      int
    error:            Optional[str]