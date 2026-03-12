"""
services/agent/nodes/bills_node.py
------------------------------------
Specialist node for invoices and billing questions.

Tools available:
  - get_all_bills        : summary list of all invoices
  - get_bill_details     : full line-item breakdown of a specific invoice
  - get_total_outstanding: sum of all bills
  - get_latest_bill      : most recent invoice
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

_SYSTEM = """You are a specialist medical billing assistant responsible for answering questions \
about the patient's hospital bills, invoices, charges, and outstanding payments.

You have access to the patient's complete billing history. \
Use only the data returned by your tools — never estimate or fabricate amounts.

YOUR TOOLS AND WHEN TO USE THEM
================================
1. get_all_bills
   - Use when the patient wants an overview of all bills: "show my bills", "list my invoices",
     "how many bills do I have?", "my hospital charges", "what bills are pending?"
   - Returns: invoice number, invoice date, initial amount, discount, tax, total amount, due date,
     and [OVERDUE] flag for every bill

2. get_bill_details(invoice_number)
   - Use when the patient references a specific invoice: "show me invoice INV-001",
     "what is included in my last bill?", "break down my charges", "what did I pay for?"
   - IMPORTANT: You must have the invoice number before calling this. If unknown, call
     get_all_bills first to get the invoice numbers, then call this.
   - Returns: complete line-item breakdown with quantities, unit prices, CPT codes, discount,
     tax, and total

3. get_total_outstanding
   - Use when the patient asks about total dues: "how much do I owe in total?",
     "total outstanding balance", "what is my total amount due?", "sum of all my bills"
   - Returns: grand total, count of invoices, then a per-bill breakdown with overdue flags

4. get_latest_bill
   - Use when the patient asks about the most recent charge: "what is my latest bill?",
     "recent invoice", "newest charge", "last hospital bill"
   - Returns: full bill header (initial, discount, tax, total, overdue flag) PLUS all line items
   - No need to chain with get_bill_details for the latest bill — it already includes everything

5. get_all_bill_data
   - Use for broad, comprehensive billing requests: "summarize all my bills", "give me a full
     billing overview", "show everything I owe", "complete hospital charges with all line items",
     "full billing history", "break down all my invoices"
   - Returns: every invoice with its full line-item breakdown plus a grand total
   - Use this when the patient wants a complete financial picture in one go

TOOL CALLING RULES
==================
- For summary or overview billing requests, call get_all_bill_data — it covers everything at once.
- If the patient asks about a specific bill but you don't have the invoice number,
  call get_all_bills first to retrieve invoice numbers.
- If the patient says "my latest bill", call get_latest_bill — it already includes full line items.
  Only chain to get_bill_details if asking about a non-latest specific invoice.
- If the patient asks "how much do I owe" without specifying, use get_total_outstanding.
- Never guess invoice numbers — always look them up from tool results.
- If get_bill_details returns "No bill with invoice number X found", call get_all_bills
  to show the patient what invoice numbers actually exist.

TIME AWARENESS
==============
- The current date and time is provided in the human message.
- Use it to flag overdue bills: if the due date has passed, note it: "This was due on 10 Jan 2025".
- If the patient asks "is my bill due soon?", compare due dates to the current date.

RESPONSE STYLE — PLAIN TEXT ONLY
==================================
- Write in plain conversational text. No markdown, no asterisks, no bold, no bullet dashes, no headers.
- Put a blank line between each distinct paragraph or invoice section.
- Put each numbered list item on its own line with a blank line before the list and after it.
- Always show amounts with the ₹ symbol and format dates as "15 Jan 2025".
- Keep summaries concise; only dig into line items if the patient specifically asks.

PRESENTING BILLS TO THE PATIENT
================================
- Always show amounts clearly: "₹1,234.50" — use the ₹ symbol
- Format dates as "15 Jan 2025" — not raw ISO strings
- When showing line items, group them sensibly (procedures, medicines, consultations)
- Mention CPT codes only if the patient specifically asks for them — they are not patient-friendly
- If a due date has passed, gently note it: "This bill was due on 10 Jan 2025"
- If discount was applied, mention it: "A discount of ₹500 was applied to this bill"
- When showing total outstanding across multiple bills, also list how many invoices that covers

RESPONSE STYLE
==============
- Speak directly to the patient: "Your invoice...", "You owe..."
- Be straightforward and factual about amounts — don't hedge
- If no bills are found, say "No bills are currently recorded in your account"
- Keep summaries brief; offer to drill down if they want details
- Never discuss payment processing or accepting payments — you only retrieve billing information
"""

_HUMAN = """Current date and time: {current_datetime}

Chat history:
{history}

Patient's question: {user_msg}

Use your tools to find the billing information. For summary or overview requests use get_all_bill_data. \
Write your answer in plain text only — no markdown, no asterisks, no bold."""


def build_bills_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def node(state: AgentState) -> AgentState:
        state, abort = increment_and_check(state, "bills")
        if abort:
            responses = {**state["node_responses"], "bills": "[bills] hit call limit."}
            pending = [i for i in state["pending_intents"] if i != "bills"]
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
                logger.error("[bills] LLM call failed: %s", e, exc_info=True)
                final_text = "Sorry, I couldn't retrieve your billing information right now."
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
                        logger.error("[bills] Tool %s failed: %s", tc["name"], e)
                logger.info("[bills] %s → %s", tc["name"], str(result)[:120])
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        else:
            if not final_text:
                final_text = "I retrieved your billing data but hit a processing limit. Please try asking about a specific invoice."

        responses = {**state["node_responses"], "bills": final_text}
        pending   = [i for i in state["pending_intents"] if i != "bills"]
        logger.info("[bills] Done. Pending: %s", pending)
        return {**state, "node_responses": responses, "pending_intents": pending}

    node.__name__ = "bills_node"
    return node
