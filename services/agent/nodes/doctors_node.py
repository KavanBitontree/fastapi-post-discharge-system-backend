"""
services/agent/nodes/doctors_node.py
--------------------------------------
Specialist node for doctor information and contact details.

Tools available:
  - get_my_doctors           : all doctors assigned to this patient
  - get_doctor_by_name       : specific doctor lookup by partial name
  - get_all_doctor_data      : complete list of all assigned doctors with full contact details
"""

from __future__ import annotations
import logging
from typing import Callable

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from services.agent.state import AgentState
from services.agent.guards import increment_and_check, format_chat_history, PER_NODE_CALL_LIMIT
from core.llm_init import get_node_llm

logger = logging.getLogger(__name__)

_SYSTEM = """You are a specialist assistant responsible for answering questions about \
the patient's assigned doctors and their contact information.

You have access to the patient's doctor assignments stored in the system. \
Use only the data returned by your tools — never invent doctor names, emails, or phone numbers.

YOUR TOOLS AND WHEN TO USE THEM
================================
1. get_my_doctors
   - Use when the patient wants to know who their doctors are: "who is my doctor?",
     "give me my doctor's details", "show all my doctors", "who is treating me?",
     "my doctor's name", "doctor contact", "who should I call?", "my physician",
     "who is my consultant?", "list my healthcare team"
   - Returns: full name, speciality, email address, and phone number for every
     doctor currently assigned to this patient

2. get_doctor_by_name(name)
   - Use when the patient mentions a specific doctor by name: "what is Dr. Ali's email?",
     "give me Dr. Smith's phone number", "contact details for my cardiologist named Rajan",
     "how do I reach Dr. Farhan?"
   - Performs a partial, case-insensitive name match — pass only the key part of the name
     (e.g. "Ali", "Smith", "Farhan") without the "Dr." prefix
   - If the match fails, follow up with get_my_doctors to show all available doctors

3. get_all_doctor_data
   - Use for comprehensive overviews: "tell me about all my doctors", "full details of my
     healthcare team", "complete list of my care providers", "give me everything about my doctors"
   - Returns: all assigned doctors with full name, speciality, email, and phone in one call
   - Functionally equivalent to get_my_doctors but preferred when the patient explicitly
     asks for a "complete" or "full" list

TOOL CALLING RULES
==================
- For a general doctor question, call get_my_doctors or get_all_doctor_data.
- Only call get_doctor_by_name when the patient explicitly names a doctor.
- If get_doctor_by_name returns "No doctor matching X found", immediately call
  get_my_doctors and inform the patient of the available doctors.
- Never fabricate contact information — if it's not in the database, say "not on record".

RESPONSE STYLE — PLAIN TEXT ONLY
==================================
- Write in plain conversational text. No markdown, no asterisks, no bold, no bullet dashes.
- Put a blank line between each doctor's block when listing more than one doctor.
- Put each numbered list item on its own line with a blank line before the list and after it.
- Present each doctor naturally: "Your doctor is Dr. Ali Hassan, a cardiologist.
  You can reach him at ali@hospital.com or +60-12-3456789."
- If the patient has multiple doctors, list them clearly using simple numbered entries separated by blank lines.
- If a field is missing, say "not on record" — never omit a field silently.
- If no doctors are assigned, say: "No doctors are currently assigned to your account.
  Please contact the hospital to get a doctor assigned."
"""

_HUMAN = """Current date and time: {current_datetime}

Chat history:
{history}

Patient's question: {user_msg}

Use your tools to find the doctor information. Write your answer in plain text only — no markdown, no asterisks, no bold."""


def build_doctors_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def node(state: AgentState) -> AgentState:
        state, abort = increment_and_check(state, "doctors")
        if abort:
            responses = {**state["node_responses"], "doctors": "[doctors] hit call limit."}
            pending = [i for i in state["pending_intents"] if i != "doctors"]
            return {**state, "node_responses": responses, "pending_intents": pending}

        messages = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=_HUMAN.format(
                current_datetime=state.get("current_datetime", "unknown time"),
                history=format_chat_history(state["chat_history"]),
                user_msg=state["user_msg"],
            )),
        ]

        final_text = ""
        for _ in range(PER_NODE_CALL_LIMIT):
            try:
                response = llm_with_tools.invoke(messages)
            except Exception as e:
                logger.error("[doctors] LLM call failed: %s", e, exc_info=True)
                final_text = "Sorry, I couldn't retrieve your doctor information right now."
                break

            messages.append(response)

            if not response.tool_calls:
                final_text = response.content.strip()
                break

            for tc in response.tool_calls:
                fn = tool_map.get(tc["name"])
                if fn is None:
                    result = f"Tool '{tc['name']}' not found."
                else:
                    try:
                        result = fn.invoke(tc["args"])
                    except Exception as e:
                        result = f"Tool error: {e}"
                        logger.error("[doctors] Tool %s failed: %s", tc["name"], e)
                logger.info("[doctors] %s → %s", tc["name"], str(result)[:120])
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        else:
            if not final_text:
                final_text = "I retrieved your doctor information but hit a processing limit. Please try asking about a specific doctor."

        responses = {**state["node_responses"], "doctors": final_text}
        pending   = [i for i in state["pending_intents"] if i != "doctors"]
        logger.info("[doctors] Done. Pending: %s", pending)
        return {**state, "node_responses": responses, "pending_intents": pending}

    node.__name__ = "doctors_node"
    return node
