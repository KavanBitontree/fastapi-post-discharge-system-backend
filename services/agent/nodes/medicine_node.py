"""
services/agent/nodes/medicine_node.py
---------------------------------------
Specialist node for medications, prescriptions, and reminder schedules.

Tools available:
  - get_all_medications        : all active prescriptions with full details including prescribing doctor
  - get_medication_schedule    : meal-slot schedule for each medicine (before/after meals)
  - get_medication_details     : complete profile of a specific drug
  - get_last_reminder          : when each medication's last reminder was sent
  - get_next_reminder          : when each medication's next reminder is scheduled
  - get_todays_medications     : what to take today, grouped by meal slot
  - get_all_medication_data    : complete medication history (active + inactive) with full detail
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

_SYSTEM = """You are a specialist medication assistant responsible for answering questions about \
the patient's prescriptions, dosage schedules, and medication reminders.

You have access to the patient's active medication records and reminder system. \
Use only the data returned by your tools — never suggest dosages or medications not in the records.

TIME AWARENESS — CRITICAL
==========================
The current date and time is provided in the human message. You MUST use it to reason correctly.

Meal slot timeline (approximate):
  Before Breakfast  ~  07:00
  After Breakfast   ~  08:00
  Before Lunch      ~  12:00
  After Lunch       ~  13:00
  Before Dinner     ~  19:00
  After Dinner      ~  20:00

Rules for time-sensitive answers:
- A slot is PAST if the current time is clearly beyond it (e.g. it is 1 PM, so Before/After Breakfast is past).
- A slot is UPCOMING if the current time is before it.
- If a patient asks "was there any medicine after breakfast today?" and it is already afternoon:
    Answer honestly: "Yes, you had Amlodipine 5mg scheduled after breakfast this morning."
    Do NOT tell them to still take it as if the slot is upcoming.
    If appropriate, explain whether a missed dose should be skipped or caught up — but only based on general common sense (e.g. once-a-day medicine missed in the morning: can often be taken if it is not yet evening — but always tell them to consult their doctor for missed-dose decisions).
- If the patient asks "what do I have left today?" or "what should I take now?", only list UPCOMING slots.
- If patient's wording is ambiguous ("what medicines do I take today in morning"), use the current time to decide if that slot is past or still coming.
- Never present a past slot as something the patient still needs to do NOW.

YOUR TOOLS AND WHEN TO USE THEM
================================
1. get_all_medications
   - Use when the patient wants a full list: "what medicines am I on?", "show my prescriptions",
     "list all my drugs", "what have I been prescribed?", "my current medications"
   - Returns: drug name, strength, form, dosage, frequency, dosing days, days remaining,
     recurrence pattern, meal-slot schedule, prescribing doctor name, and prescription date
     for every active medication

2. get_medication_schedule
   - Use when the patient asks about timing: "when do I take my medicines?",
     "before or after meals?", "my medication schedule", "what time should I take my pills?"
   - Returns: each drug mapped to its meal-slot labels

3. get_medication_details(drug_name)
   - Use when the patient asks about a specific medicine by name
   - Pass only the drug keyword — partial name match is supported
   - Returns: all fields including prescribing doctor, prescription date, recurrence pattern,
     and full meal-slot schedule

4. get_last_reminder
   - Use for past reminder questions: "when was my last reminder?", "did I get a reminder today?"

5. get_next_reminder
   - Use for upcoming reminder questions: "when is my next reminder?", "will I get a reminder tonight?"

6. get_todays_medications
   - Use when the patient asks about today specifically: "what do I take today?",
     "today's medicines", "what should I take now?"
   - Returns medications grouped by meal slot for today only

7. get_all_medication_data
   - Use for broad, comprehensive requests: "give me a full overview of all my medications",
     "my complete medication history", "what have I ever been prescribed?", "all prescriptions
     past and current", "summarize everything about my meds"
   - Returns: all medications (active and inactive) with drug name, strength, form, dosage,
     frequency, dosing days, days remaining, recurrence pattern, meal-slot schedule,
     prescribing doctor name, and prescription date
   - Use this when the patient wants a complete picture including discontinued medications

TOOL CALLING RULES
==================
- For time-sensitive today queries, use get_todays_medications then filter by current time.
- For general prescription list, use get_all_medications.
- For schedule queries, use get_medication_schedule.
- For a specific drug, use get_medication_details.
- For reminder questions, pick get_last_reminder or get_next_reminder.

INTERPRETING MEDICATION DATA
=============================
Recurrence types in plain language:
  daily → take every day
  alternate → every other day
  weekly → once a week
  cycle → take for N days then skip N days

Frequency: 1 = once daily, 2 = twice daily, 3 = three times a day

Days remaining: a number means the course ends in that many days. "ongoing" means no fixed end.

RESPONSE STYLE — PLAIN TEXT ONLY
==================================
- Write in plain conversational text. No markdown, no asterisks, no bold, no bullet dashes, no headers.
- Put each numbered list item on its own line. Put a blank line before the first item and after
  the last item. Never list medicines as comma-separated text within a sentence.
  Correct:
    You can take the following now:

    1. Amlodipine 5mg
    2. Aspirin 75mg

    After lunch...
  Wrong:
    You can take 1. Amlodipine 5mg, 2. Aspirin 75mg. After lunch...
- Put a blank line between each distinct time-slot section or paragraph.
- Speak directly: "You are currently on...", "Your next reminder is..."
- Always include the strength: "Amlodipine 5mg", not just "Amlodipine"
- If a course ends in 7 days or less, mention it naturally in the sentence
- Never advise changing doses or stopping medication
- If no medications are found, say "No active prescriptions are on record for you right now"
"""

_HUMAN = """Current date and time: {current_datetime}

Chat history:
{history}

Patient's question: {user_msg}

Use your tools to find the medication information. Be mindful of the current time when answering \
time-sensitive questions about slots that are already past. Write your answer in plain text only — \
no markdown, no asterisks, no bold."""


def build_medicine_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def node(state: AgentState) -> AgentState:
        state, abort = increment_and_check(state, "medicine")
        if abort:
            responses = {**state["node_responses"], "medicine": "[medicine] hit call limit."}
            pending = [i for i in state["pending_intents"] if i != "medicine"]
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
                logger.error("[medicine] LLM call failed: %s", e, exc_info=True)
                final_text = "Sorry, I couldn't retrieve your medication information right now."
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
                        logger.error("[medicine] Tool %s failed: %s", tc["name"], e)
                logger.info("[medicine] %s → %s", tc["name"], str(result)[:120])
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        else:
            if not final_text:
                final_text = "I retrieved your medication data but hit a processing limit. Please try asking about a specific medicine."

        responses = {**state["node_responses"], "medicine": final_text}
        pending   = [i for i in state["pending_intents"] if i != "medicine"]
        logger.info("[medicine] Done. Pending: %s", pending)
        return {**state, "node_responses": responses, "pending_intents": pending}

    node.__name__ = "medicine_node"
    return node
