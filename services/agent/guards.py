"""
services/agent/guards.py
-------------------------
Loop protection and shared helpers used across all nodes.
"""

from __future__ import annotations
from services.agent.state import AgentState

# ── Limits ────────────────────────────────────────────────────────────────────
GLOBAL_CALL_LIMIT   = 10   # total LLM calls across the entire graph
PER_NODE_CALL_LIMIT = 3    # max times a single node can call its LLM


def increment_and_check(state: AgentState, node_name: str) -> tuple[AgentState, bool]:
    """
    Increment call counters for *node_name*.
    Returns (updated_state, should_abort).

    should_abort=True means the caller must stop looping and return immediately.
    """
    counts = dict(state["call_counts"])
    counts[node_name] = counts.get(node_name, 0) + 1
    total = state["total_calls"] + 1

    updated = {**state, "call_counts": counts, "total_calls": total}

    per_node_hit = counts[node_name] >= PER_NODE_CALL_LIMIT
    global_hit   = total >= GLOBAL_CALL_LIMIT

    if per_node_hit or global_hit:
        reason = (
            f"Node '{node_name}' reached its call limit ({PER_NODE_CALL_LIMIT})"
            if per_node_hit
            else f"Global call limit ({GLOBAL_CALL_LIMIT}) reached"
        )
        updated["error"] = reason
        return updated, True

    return updated, False


def format_chat_history(history: list[dict]) -> str:
    """Format chat_history list into a readable string for LLM prompts."""
    if not history:
        return "No previous conversation."
    lines = []
    for turn in history:
        role = "Patient" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)