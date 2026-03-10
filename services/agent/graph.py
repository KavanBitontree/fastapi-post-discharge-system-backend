"""
services/agent/graph.py
------------------------
Builds and compiles the LangGraph for each request.

Graph topology:
  START
    → supervisor_router     (classifies intents, dispatches to first specialist)
        → END               (off-topic / error / global limit)
        → [specialist]      (first pending intent)

  Every specialist always returns to:
    → supervisor_checker    (called after EVERY specialist node — no cross-edges)
        → [specialist]      (if more pending intents remain)
        → [specialist]      (if LLM validation found a gap — re-queue)
        → supervisor_synthesizer  (when all intents satisfied)

    → supervisor_synthesizer  (combines all answers into one response)
    → END

Loop guards:
  - Per-node: PER_NODE_CALL_LIMIT (3) inside each specialist
  - Global: GLOBAL_CALL_LIMIT (10) tracked in state.total_calls
"""

from __future__ import annotations
import logging
from sqlalchemy.orm import Session

from langgraph.graph import StateGraph, END

from services.agent.state import AgentState
from services.agent.nodes.supervisor import (
    supervisor_router,
    supervisor_checker,
    supervisor_synthesizer,
)
from services.agent.nodes.reports_node import build_reports_node
from services.agent.nodes.bills_node import build_bills_node
from services.agent.nodes.medicine_node import build_medicine_node
from services.agent.nodes.doctors_node import build_doctors_node
from services.agent.tools import build_report_tools, build_bill_tools, build_medicine_tools, build_doctor_tools

logger = logging.getLogger(__name__)

# ── Node names (constants to avoid typos) ────────────────────────────────────
N_ROUTER     = "supervisor_router"
N_CHECKER    = "supervisor_checker"
N_REPORTS    = "reports_node"
N_BILLS      = "bills_node"
N_MEDICINE   = "medicine_node"
N_DOCTORS    = "doctors_node"
N_SYNTHESIZE = "supervisor_synthesizer"

SPECIALIST_NODES = [N_REPORTS, N_BILLS, N_MEDICINE, N_DOCTORS]
INTENT_TO_NODE   = {
    "reports":  N_REPORTS,
    "bills":    N_BILLS,
    "medicine": N_MEDICINE,
    "doctors":  N_DOCTORS,
}


# ── Conditional edge functions ────────────────────────────────────────────────

def route_after_supervisor(state: AgentState) -> str:
    """
    After supervisor_router: dispatch to first pending specialist,
    or END if off-topic / error / global limit hit.
    """
    if state.get("error") or state.get("total_calls", 0) >= 10:
        return END

    pending = state.get("pending_intents", [])
    if not pending or pending == ["end"]:
        return N_SYNTHESIZE  # ← let synthesis LLM respond warmly instead of hard END

    return INTENT_TO_NODE.get(pending[0], END)


def route_after_checker(state: AgentState) -> str:
    """
    After supervisor_checker:
      - If pending_intents is non-empty → dispatch to next specialist.
      - If empty → all topics answered, proceed to synthesis.
      - On error / global limit → synthesize what we have.
    """
    if state.get("error") or state.get("total_calls", 0) >= 10:
        return N_SYNTHESIZE

    pending = [i for i in state.get("pending_intents", []) if i in INTENT_TO_NODE]
    if pending:
        return INTENT_TO_NODE[pending[0]]
    return N_SYNTHESIZE


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_agent_graph(discharge_id: int, db: Session) -> StateGraph:
    """
    Build a compiled LangGraph for a single discharge request.

    Called once per request — tools are bound to the
    discharge's DB session and discharge_id at build time.
    """
    # Build tools bound to this discharge + session
    report_tools   = build_report_tools(discharge_id, db)
    bill_tools     = build_bill_tools(discharge_id, db)
    medicine_tools = build_medicine_tools(discharge_id, db)
    doctor_tools   = build_doctor_tools(discharge_id, db)

    # Build specialist node functions
    reports_node  = build_reports_node(report_tools)
    bills_node    = build_bills_node(bill_tools)
    medicine_node = build_medicine_node(medicine_tools)
    doctors_node  = build_doctors_node(doctor_tools)

    # ── Assemble graph ────────────────────────────────────────────────────────
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node(N_ROUTER,     supervisor_router)
    graph.add_node(N_CHECKER,    supervisor_checker)
    graph.add_node(N_REPORTS,    reports_node)
    graph.add_node(N_BILLS,      bills_node)
    graph.add_node(N_MEDICINE,   medicine_node)
    graph.add_node(N_DOCTORS,    doctors_node)
    graph.add_node(N_SYNTHESIZE, supervisor_synthesizer)

    # Entry point
    graph.set_entry_point(N_ROUTER)

    # supervisor_router → first specialist or END
    graph.add_conditional_edges(
        N_ROUTER,
        route_after_supervisor,
        {
            N_REPORTS: N_REPORTS,
            N_BILLS:   N_BILLS,
            N_MEDICINE: N_MEDICINE,
            N_DOCTORS: N_DOCTORS,
            N_SYNTHESIZE: N_SYNTHESIZE,
            END:       END,
        },
    )

    # Every specialist → supervisor_checker (unconditional — no cross-edges)
    for node_name in SPECIALIST_NODES:
        graph.add_edge(node_name, N_CHECKER)

    # supervisor_checker → next specialist or synthesizer
    graph.add_conditional_edges(
        N_CHECKER,
        route_after_checker,
        {
            N_REPORTS:    N_REPORTS,
            N_BILLS:      N_BILLS,
            N_MEDICINE:   N_MEDICINE,
            N_DOCTORS:    N_DOCTORS,
            N_SYNTHESIZE: N_SYNTHESIZE,
        },
    )

    # Synthesizer → END always
    graph.add_edge(N_SYNTHESIZE, END)

    return graph.compile()