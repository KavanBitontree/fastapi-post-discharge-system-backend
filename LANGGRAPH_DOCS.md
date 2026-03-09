# LangGraph Agent — Complete Technical Documentation

> **Post-Discharge Medical Assistant — How the AI Brain Works**
>
> This document explains every piece of the LangGraph system from scratch.
> No prior LangGraph experience is needed.

---

## Table of Contents

1. [What Problem Does This Solve?](#1-what-problem-does-this-solve)
2. [What is LangGraph? (For Beginners)](#2-what-is-langgraph-for-beginners)
3. [Bird's-Eye Architecture](#3-birds-eye-architecture)
4. [The Shared State — `AgentState`](#4-the-shared-state--agentstate)
5. [Loop Protection — `guards.py`](#5-loop-protection--guardspy)
6. [LLM Configuration — `llm_init.py`](#6-llm-configuration--llm_initpy)
7. [The Graph — `graph.py`](#7-the-graph--graphpy)
8. [Supervisor Node — `supervisor.py`](#8-supervisor-node--supervisorpy)
   - [Pass 1: Router](#pass-1-supervisor_router)
   - [Pass 2: Checker](#pass-2-supervisor_checker)
   - [Pass 3: Synthesizer](#pass-3-supervisor_synthesizer)
9. [Specialist Nodes](#9-specialist-nodes)
   - [Reports Node](#91-reports-node)
   - [Bills Node](#92-bills-node)
   - [Medicine Node](#93-medicine-node)
   - [Doctors Node](#94-doctors-node)
10. [Tools — The Database Hands](#10-tools--the-database-hands)
    - [Report Tools (6 tools)](#101-report-tools)
    - [Bill Tools (5 tools)](#102-bill-tools)
    - [Medicine Tools (7 tools)](#103-medicine-tools)
    - [Doctor Tools (3 tools)](#104-doctor-tools)
11. [Chat History Service](#11-chat-history-service)
12. [API Entry Point — `chat_routes.py`](#12-api-entry-point--chat_routespy)
13. [End-to-End Request Flow](#13-end-to-end-request-flow)
14. [File Structure Reference](#14-file-structure-reference)

---

## 1. What Problem Does This Solve?

When a patient is discharged from hospital, they often have questions like:

- *"What did my blood test show?"*
- *"How much do I owe the hospital?"*
- *"When do I take my medicines?"*
- *"What's my doctor's phone number?"*

These questions span **4 completely different domains** — Lab Reports, Billing, Medications, and Doctors. Rather than building one massive monolithic chatbot that knows everything poorly, this system uses a **team of specialist AI agents**, each expert in one domain, coordinated by a Supervisor.

---

## 2. What is LangGraph? (For Beginners)

**LangGraph** is a Python library for building AI workflows as a **directed graph** (think flowchart).

### Core Concepts

| Concept | What it means |
|---|---|
| **Node** | A function that reads the current state, does work (calls an LLM or tools), and updates the state |
| **Edge** | An arrow connecting two nodes — tells the graph "after Node A, go to Node B" |
| **Conditional Edge** | A smart arrow where the *destination* depends on the state — "after Node A, go to B *or* C depending on what happened" |
| **State** | A shared Python dictionary that every node can read from and write to |
| **Graph** | The assembled collection of nodes and edges, compiled into a runnable object |

### Analogy: A Hospital With Specialists

Imagine you walk into a hospital reception. The **receptionist** (Supervisor Router) reads your complaint and sends you to the right specialist wing. Each **specialist doctor** (Reports / Bills / Medicine / Doctors nodes) examines your records and writes up their findings. Then the **discharge nurse** (Synthesizer) reads all the notes and gives you one clear summary. A **quality checker** (Checker) makes sure nothing was missed before you're discharged.

---

## 3. Bird's-Eye Architecture

```
Patient's HTTP Request (POST /api/chat)
          │
          ▼
┌─────────────────────┐
│   chat_routes.py    │  ← Validates patient, builds initial state
│   (FastAPI route)   │
└────────┬────────────┘
         │ graph.invoke(initial_state)
         ▼
┌════════════════════════════════════════════════════════════╗
║                    LANGGRAPH GRAPH                         ║
║                                                            ║
║   START                                                    ║
║     │                                                      ║
║     ▼                                                      ║
║  ┌──────────────────┐                                      ║
║  │ supervisor_router│  ← "What does the patient want?"     ║
║  └──────┬───────────┘    Outputs: intents = ["reports",   ║
║         │                          "bills", ...]           ║
║         │ (conditional edge — goto first intent's node)   ║
║         ▼                                                  ║
║  ┌─────────────────────────────────────────────────────┐  ║
║  │  Specialist Nodes (run one at a time, in sequence)  │  ║
║  │                                                     │  ║
║  │   ┌────────────┐   ┌────────────┐                   │  ║
║  │   │reports_node│   │ bills_node │                   │  ║
║  │   └────────────┘   └────────────┘                   │  ║
║  │   ┌──────────────┐ ┌─────────────┐                  │  ║
║  │   │medicine_node │ │doctors_node │                   │  ║
║  │   └──────────────┘ └─────────────┘                  │  ║
║  │                                                     │  ║
║  │   Each node: calls LLM → LLM calls tools → DB data  │  ║
║  └─────────────────────────┬───────────────────────────┘  ║
║         │ (every specialist always goes here)             ║
║         ▼                                                  ║
║  ┌──────────────────┐                                      ║
║  │supervisor_checker│  ← "Was anything missed?"           ║
║  └──────┬───────────┘                                      ║
║         │                                                  ║
║         ├─ more intents pending? → back to specialist     ║
║         │                                                  ║
║         ▼                                                  ║
║  ┌───────────────────────┐                                 ║
║  │supervisor_synthesizer │  ← "Write one clean answer"    ║
║  └──────────┬────────────┘                                 ║
║             │                                              ║
║            END                                             ║
╚════════════════════════════════════════════════════════════╝
         │
         ▼
   final_answer  (returned to patient)
```

---

## 4. The Shared State — `AgentState`

**File:** `services/agent/state.py`

This is the "clipboard" that every node reads from and writes to. It is a Python `TypedDict` — a dictionary with declared field types.

```python
class AgentState(TypedDict):
    patient_id:       int          # Who is talking — never changes
    user_msg:         str          # The patient's original message
    current_datetime: str          # e.g. "Monday, 09 Mar 2026, 02:15 PM IST"
    chat_history:     list[dict]   # Last 10 conversation turns [{"role": ..., "content": ...}]
    intents:          list[str]    # What supervisor decided: ["reports", "bills"]
    pending_intents:  list[str]    # Intents not yet handled — shrinks as nodes finish
    node_responses:   dict[str,str]# Each node writes its answer here: {"reports": "...", ...}
    final_answer:     Optional[str]# The final patient-facing answer (written by synthesizer)
    call_counts:      dict[str,int]# Per-node call counter: {"supervisor": 2, "reports": 1}
    total_calls:      int          # Total LLM calls across the whole graph
    error:            Optional[str]# Set if something goes wrong
```

### How State Flows

Every node function receives the full `state` dictionary and **must return a new version of it** with any changes. LangGraph merges the returned dict back into the running state.

```python
# Example: a node removes its own intent from pending_intents and adds its answer
def my_node(state: AgentState) -> AgentState:
    # ... do work ...
    return {
        **state,                                    # keep everything else unchanged
        "node_responses": {
            **state["node_responses"],
            "reports": "Your haemoglobin is 14.6"  # add this node's answer
        },
        "pending_intents": [                        # remove "reports" from pending
            i for i in state["pending_intents"] if i != "reports"
        ]
    }
```

---

## 5. Loop Protection — `guards.py`

**File:** `services/agent/guards.py`

LLM calls cost money and can loop forever if something goes wrong. Two limits protect the system:

```python
GLOBAL_CALL_LIMIT   = 10   # Max total LLM calls for the ENTIRE graph run
PER_NODE_CALL_LIMIT = 3    # Max times a single specialist node can call its LLM
```

### `increment_and_check(state, node_name)`

Every node calls this **first thing** before doing any LLM work.

```python
def increment_and_check(state: AgentState, node_name: str) -> tuple[AgentState, bool]:
    """
    Increments call counters.
    Returns (updated_state, should_abort).
    If should_abort=True, the node must stop and return immediately.
    """
    counts = dict(state["call_counts"])
    counts[node_name] = counts.get(node_name, 0) + 1
    total = state["total_calls"] + 1

    updated = {**state, "call_counts": counts, "total_calls": total}

    per_node_hit = counts[node_name] >= PER_NODE_CALL_LIMIT
    global_hit   = total >= GLOBAL_CALL_LIMIT

    if per_node_hit or global_hit:
        updated["error"] = "... limit reason ..."
        return updated, True  # abort=True

    return updated, False    # abort=False → safe to proceed
```

### `format_chat_history(history)`

Converts the list of `{"role": ..., "content": ...}` dicts into a human-readable string for inclusion in LLM prompts.

```python
# Input:  [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]
# Output: "Patient: hi\nAssistant: Hello!"
```

---

## 6. LLM Configuration — `llm_init.py`

**File:** `core/llm_init.py`

Two different LLM sizes are used — a heavier model for the supervisor (complex reasoning) and a lighter model for specialist nodes (focused tool calling).

```python
SUPERVISOR_MODEL = "openai/gpt-oss-120b"   # Heavy — complex routing + synthesis
NODE_MODEL       = "openai/gpt-oss-20b"    # Lighter — specialist tool calling

def get_supervisor_llm() -> ChatGroq:
    """Used by: supervisor_router, supervisor_checker, supervisor_synthesizer"""
    return ChatGroq(
        model=SUPERVISOR_MODEL,
        temperature=0.2,    # Low temp = more deterministic routing decisions
        max_tokens=4096,
        api_key=settings.GROQ_API_KEY,
    )

def get_node_llm() -> ChatGroq:
    """Used by: reports_node, bills_node, medicine_node, doctors_node"""
    return ChatGroq(
        model=NODE_MODEL,
        temperature=0.1,    # Very low temp = consistent tool selection
        max_tokens=4096,
        api_key=settings.GROQ_API_KEY,
    )
```

**Provider:** [Groq](https://groq.com) — used for fast inference.

---

## 7. The Graph — `graph.py`

**File:** `services/agent/graph.py`

This file **wires everything together**. It builds the `StateGraph`, registers all nodes, and defines all edges.

### Node Name Constants

```python
N_ROUTER     = "supervisor_router"
N_CHECKER    = "supervisor_checker"
N_REPORTS    = "reports_node"
N_BILLS      = "bills_node"
N_MEDICINE   = "medicine_node"
N_DOCTORS    = "doctors_node"
N_SYNTHESIZE = "supervisor_synthesizer"

INTENT_TO_NODE = {
    "reports":  N_REPORTS,
    "bills":    N_BILLS,
    "medicine": N_MEDICINE,
    "doctors":  N_DOCTORS,
}
```

### `build_agent_graph(patient_id, db)`

Called **once per HTTP request**. It creates tool instances bound to the patient's ID and database session, then assembles and compiles the graph.

```python
def build_agent_graph(patient_id: int, db: Session) -> StateGraph:
    # 1. Build tools — each tool factory closes over patient_id and db
    report_tools   = build_report_tools(patient_id, db)     # 6 tools
    bill_tools     = build_bill_tools(patient_id, db)       # 5 tools
    medicine_tools = build_medicine_tools(patient_id, db)   # 7 tools
    doctor_tools   = build_doctor_tools(patient_id, db)     # 3 tools

    # 2. Build node functions — each node closes over its tool list
    reports_node  = build_reports_node(report_tools)
    bills_node    = build_bills_node(bill_tools)
    medicine_node = build_medicine_node(medicine_tools)
    doctors_node  = build_doctors_node(doctor_tools)

    # 3. Assemble the graph
    graph = StateGraph(AgentState)

    # Register every node with a name and its function
    graph.add_node(N_ROUTER,     supervisor_router)
    graph.add_node(N_CHECKER,    supervisor_checker)
    graph.add_node(N_REPORTS,    reports_node)
    graph.add_node(N_BILLS,      bills_node)
    graph.add_node(N_MEDICINE,   medicine_node)
    graph.add_node(N_DOCTORS,    doctors_node)
    graph.add_node(N_SYNTHESIZE, supervisor_synthesizer)

    # 4. Set where the graph starts
    graph.set_entry_point(N_ROUTER)

    # 5. After supervisor_router: go to first specialist (or END)
    graph.add_conditional_edges(
        N_ROUTER,
        route_after_supervisor,        # ← decision function
        { N_REPORTS: N_REPORTS, N_BILLS: N_BILLS, ... END: END }
    )

    # 6. Every specialist → always goes to checker (no exceptions)
    for node_name in [N_REPORTS, N_BILLS, N_MEDICINE, N_DOCTORS]:
        graph.add_edge(node_name, N_CHECKER)

    # 7. After checker: next specialist OR synthesizer
    graph.add_conditional_edges(
        N_CHECKER,
        route_after_checker,           # ← decision function
        { N_REPORTS: N_REPORTS, ..., N_SYNTHESIZE: N_SYNTHESIZE }
    )

    # 8. Synthesizer always ends the graph
    graph.add_edge(N_SYNTHESIZE, END)

    return graph.compile()
```

### Conditional Edge Logic

```python
def route_after_supervisor(state: AgentState) -> str:
    """After router: go to first pending specialist, or synthesizer/END."""
    if state.get("error") or state.get("total_calls", 0) >= 10:
        return END
    pending = state.get("pending_intents", [])
    if not pending or pending == ["end"]:
        return N_SYNTHESIZE   # greeting or off-topic → synthesizer handles it warmly
    return INTENT_TO_NODE.get(pending[0], END)


def route_after_checker(state: AgentState) -> str:
    """After checker: dispatch next specialist or go to synthesis."""
    if state.get("error") or state.get("total_calls", 0) >= 10:
        return N_SYNTHESIZE
    pending = [i for i in state.get("pending_intents", []) if i in INTENT_TO_NODE]
    if pending:
        return INTENT_TO_NODE[pending[0]]   # still work to do
    return N_SYNTHESIZE                      # all done
```

---

## 8. Supervisor Node — `supervisor.py`

**File:** `services/agent/nodes/supervisor.py`

The supervisor has **three distinct roles**, each implemented as a separate function.

---

### Pass 1: `supervisor_router`

**Purpose:** Read the patient's message and decide which specialist(s) should handle it.

**When called:** At the very START of every graph run.

**LLM used:** `get_supervisor_llm()` (gpt-oss-120b)

**Output:** Writes `intents` and `pending_intents` into state.

```python
def supervisor_router(state: AgentState) -> AgentState:
    state, abort = increment_and_check(state, "supervisor")
    if abort:
        return {**state, "intents": ["end"], "pending_intents": ["end"]}

    llm = get_supervisor_llm()
    messages = [
        SystemMessage(content=_ROUTING_SYSTEM),   # detailed routing prompt
        HumanMessage(content=_ROUTING_HUMAN.format(
            user_msg=state["user_msg"],
            history=format_chat_history(state["chat_history"]),
        )),
    ]

    response = llm.invoke(messages)
    # LLM output is ALWAYS raw JSON: {"intents": ["reports", "bills"]}
    parsed  = json.loads(response.content.strip())
    intents = parsed.get("intents", ["end"])

    return {
        **state,
        "intents":         intents,
        "pending_intents": intents.copy(),  # pending starts as a full copy
    }
```

**What the routing prompt teaches the LLM:**

| Patient Message | Routed To |
|---|---|
| `"what are my blood test results?"` | `["reports"]` |
| `"how much do I owe?"` | `["bills"]` |
| `"what medicines am I on and who is my doctor?"` | `["medicine", "doctors"]` |
| `"give me a full summary of everything"` | `["reports", "bills", "medicine", "doctors"]` |
| `"hi"` / `"hello"` | `["end"]` (pure greeting) |
| `"what's the weather?"` | `["end"]` (off-topic) |

The routing system prompt contains an exhaustive keyword list for each specialist so the LLM never misroutes. For example, `reports` keywords include specific analyte names like `neutrophil`, `haematocrit`, `ALT`, `bilirubin` so CBC/chemistry questions are never missed.

---

### Pass 2: `supervisor_checker`

**Purpose:** Called after every specialist node finishes. Checks if the patient's full question has been answered or if any topic was missed.

**When called:** After EVERY specialist node completes (enforced by unconditional edges in the graph).

**Two behaviours:**

```
Case A: pending_intents is non-empty
    → Just pass through. The conditional edge will dispatch the next specialist.
    → No LLM call needed.

Case B: pending_intents is empty (all planned nodes ran)
    → Call LLM to validate: "Was everything the patient asked actually answered?"
    → If gaps found: re-queue missing intents.
    → If all satisfied: clear pending (→ synthesizer).
```

```python
def supervisor_checker(state: AgentState) -> AgentState:
    state, abort = increment_and_check(state, "checker")
    if abort:
        return state

    pending = [i for i in state.get("pending_intents", []) if i in _valid]

    # Case A: still nodes left to run — nothing to check yet
    if pending:
        return {**state, "pending_intents": pending}

    # Case B: everything ran — validate with LLM
    llm = get_supervisor_llm()
    messages = [
        SystemMessage(content=_CHECKER_SYSTEM),
        HumanMessage(content=_CHECKER_HUMAN.format(
            user_msg=state["user_msg"],
            responses_so_far=collected_responses_text,
        )),
    ]
    response = llm.invoke(messages)
    parsed  = json.loads(response.content)
    missing = parsed.get("missing", [])

    # Only re-queue domains not already answered
    already = set(state["node_responses"].keys())
    missing = [i for i in missing if i in _valid and i not in already]

    if missing:
        return {**state, "pending_intents": missing}  # re-dispatch
    return {**state, "pending_intents": []}            # → synthesizer
```

**Key rule in the checker prompt:** `"No data found"` and `"No bills found"` ARE valid answers. The checker only re-routes if a topic was genuinely NEVER queried at all.

---

### Pass 3: `supervisor_synthesizer`

**Purpose:** Collect all the specialist answers stored in `node_responses` and write one single, clean, patient-friendly response.

**When called:** After checker confirms all topics are satisfied.

**LLM used:** `get_supervisor_llm()` (gpt-oss-120b)

**Output:** Writes `final_answer` into state.

```python
def supervisor_synthesizer(state: AgentState) -> AgentState:
    state, abort = increment_and_check(state, "supervisor")
    if abort:
        return {**state, "final_answer": state.get("error") or "Sorry, try again."}

    llm = get_supervisor_llm()

    # Format all collected specialist answers
    responses_text = "\n\n".join(
        f"[{domain.upper()}]\n{answer}"
        for domain, answer in state["node_responses"].items()
    )

    messages = [
        SystemMessage(content=_SYNTHESIS_SYSTEM),
        HumanMessage(content=_SYNTHESIS_HUMAN.format(
            current_datetime=state["current_datetime"],
            history=format_chat_history(state["chat_history"]),
            user_msg=state["user_msg"],
            node_responses=responses_text,
        )),
    ]

    response = llm.invoke(messages)
    return {**state, "final_answer": response.content.strip()}
```

**What the synthesis prompt teaches the LLM:**
- Write in plain conversational text (no markdown, no asterisks, no bold)
- Lead with clinically urgent information (abnormal results first)
- Use blank lines between sections for readability
- Never mention agents, nodes, tools, or the database
- Never invent data — if a domain returned nothing, say so briefly

---

## 9. Specialist Nodes

All four specialist nodes follow an **identical pattern**:

```
1. Call increment_and_check → abort if limit hit
2. Build messages: [SystemMessage(prompt), HumanMessage(patient question)]
3. Loop up to PER_NODE_CALL_LIMIT (3) times:
   a. Call LLM
   b. If LLM returned no tool calls → it gave a text answer → break
   c. If LLM called tools → execute each tool against the database
   d. Append tool results back to messages → loop again
4. Store final text in state["node_responses"][domain]
5. Remove own intent from pending_intents
6. Return updated state
```

This pattern is called a **ReAct loop** (Reason → Act → Observe → Reason again).

---

### 9.1 Reports Node

**File:** `services/agent/nodes/reports_node.py`

**Domain:** Lab tests, blood work, diagnostic reports, abnormal results

**Tools available:** `get_all_reports`, `get_report_details`, `get_abnormal_results`, `get_latest_report`, `get_results_by_section`, `get_all_report_data`

```python
def build_reports_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()                    # gpt-oss-20b
    llm_with_tools = llm.bind_tools(tools)  # LLM now "knows" about all 6 tools
    tool_map = {t.name: t for t in tools}   # name → tool function lookup

    def node(state: AgentState) -> AgentState:
        state, abort = increment_and_check(state, "reports")
        if abort:
            responses = {**state["node_responses"], "reports": "[reports] hit call limit."}
            pending   = [i for i in state["pending_intents"] if i != "reports"]
            return {**state, "node_responses": responses, "pending_intents": pending}

        messages = [
            SystemMessage(content=_SYSTEM),   # full reports system prompt
            HumanMessage(content=_HUMAN.format(
                current_datetime=state.get("current_datetime"),
                history=format_chat_history(state["chat_history"]),
                user_msg=state["user_msg"],
            )),
        ]

        final_text = ""
        for _ in range(PER_NODE_CALL_LIMIT):   # max 3 LLM calls
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                # LLM gave a text answer — we're done
                final_text = response.content.strip()
                break

            # LLM decided to call one or more tools
            for tc in response.tool_calls:
                fn     = tool_map.get(tc["name"])
                result = fn.invoke(tc["args"])  # actually queries the database
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            # loop continues — LLM sees the tool results and can answer or call more tools

        # Write result back to state
        responses = {**state["node_responses"], "reports": final_text}
        pending   = [i for i in state["pending_intents"] if i != "reports"]
        return {**state, "node_responses": responses, "pending_intents": pending}

    node.__name__ = "reports_node"
    return node
```

**Key prompt rules:**
- **ALWAYS call a tool** before answering any specific test question — never answer from general medical knowledge
- `get_report_details` searches 3 levels automatically: report name → section → test name
- Flag meanings: `H` = High, `L` = Low, `**` = Critical/Panic value → always recommend seeing doctor
- Present reference ranges alongside abnormal values so the patient understands context

---

### 9.2 Bills Node

**File:** `services/agent/nodes/bills_node.py`

**Domain:** Invoices, charges, outstanding payments, billing summaries

**Tools available:** `get_all_bills`, `get_bill_details`, `get_total_outstanding`, `get_latest_bill`, `get_all_bill_data`

```python
def build_bills_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def node(state: AgentState) -> AgentState:
        # ... exact same ReAct loop pattern as reports_node ...
        # Stores answer in state["node_responses"]["bills"]
        # Removes "bills" from pending_intents

    node.__name__ = "bills_node"
    return node
```

**Key prompt rules:**
- Always show amounts with the ₹ symbol
- Format dates as "15 Jan 2025" (not raw ISO strings)
- If due date has passed, flag it: `"This bill was due on 10 Jan 2025 [OVERDUE]"`
- Mention discounts when applied

---

### 9.3 Medicine Node

**File:** `services/agent/nodes/medicine_node.py`

**Domain:** Prescriptions, dosage schedules, medication reminders

**Tools available:** `get_all_medications`, `get_medication_schedule`, `get_medication_details`, `get_last_reminder`, `get_next_reminder`, `get_todays_medications`, `get_all_medication_data`

```python
def build_medicine_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def node(state: AgentState) -> AgentState:
        # ... exact same ReAct loop pattern ...
        # Stores answer in state["node_responses"]["medicine"]
        # Removes "medicine" from pending_intents

    node.__name__ = "medicine_node"
    return node
```

**Key prompt rules (critical time-awareness):**
- The current time is injected into every prompt
- Approximate meal slot times: Breakfast ~7–8 AM, Lunch ~12–1 PM, Dinner ~7–8 PM
- If a slot is already past (it's 2 PM, so breakfast slot is past), say "you had X this morning" — **not** "you should take X now"
- Never advise changing or stopping medication — only report what the records say
- Always include drug strength: "Amlodipine **5mg**" not just "Amlodipine"

---

### 9.4 Doctors Node

**File:** `services/agent/nodes/doctors_node.py`

**Domain:** Assigned doctors, contact information, specialities

**Tools available:** `get_my_doctors`, `get_doctor_by_name`, `get_all_doctor_data`

```python
def build_doctors_node(tools: list[BaseTool]) -> Callable[[AgentState], AgentState]:
    llm = get_node_llm()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    def node(state: AgentState) -> AgentState:
        # ... exact same ReAct loop pattern ...
        # Stores answer in state["node_responses"]["doctors"]
        # Removes "doctors" from pending_intents

    node.__name__ = "doctors_node"
    return node
```

**Key prompt rules:**
- Never fabricate contact details — if a field is missing from the DB, say "not on record"
- If `get_doctor_by_name` returns no match, immediately call `get_my_doctors` and show all available
- Present each doctor as a natural sentence: *"Your doctor is Dr. Ali Hassan, a cardiologist. You can reach him at ali@hospital.com or +60-12-..."*

---

## 10. Tools — The Database Hands

Tools are the **only way** the LLMs can access the database. No LLM is ever given a database connection directly — it can only call named tools, which are Python functions that run SQLAlchemy queries.

### How Tool Calling Works

```
LLM thinks: "I need the patient's blood test results"
LLM outputs: tool_call = { "name": "get_report_details", "args": {"report_name": "CBC"} }

Node code:
    fn = tool_map["get_report_details"]
    result = fn.invoke({"report_name": "CBC"})
    # result is a string of formatted DB data

LLM sees the result in next iteration → writes final answer
```

### Tool Factory Pattern

All tool lists are built by **factory functions** that close over `patient_id` and `db`:

```python
def build_report_tools(patient_id: int, db: Session) -> list:
    # patient_id and db are captured in the closure below
    @tool
    def get_all_reports() -> str:
        # This function "knows" patient_id and db without being passed them
        reports = db.query(Report).filter(Report.patient_id == patient_id).all()
        ...
    return [get_all_reports, get_report_details, ...]
```

This means every graph run gets its own isolated tool set — no cross-patient data leakage.

---

### 10.1 Report Tools

**File:** `services/agent/tools/report_tools.py`

**Models used:** `Report`, `ReportDescription`

#### Shared Row Formatter: `_desc_line(d, report)`

Every tool that returns test results uses this formatter to produce a rich, consistently formatted line:

```python
def _desc_line(d: ReportDescription, report: Report | None = None) -> str:
    """
    Output example:
      • Haemoglobin [HAEMATOLOGY] — Result: 14.6 g/dL | Status: Normal | Ref range: 13.0–18.0 g/dL | From: CBC Full Blood Count (03 Mar 2026)
      • Neutrophils [HAEMATOLOGY] — Result: 8.2 x10⁹/L | Status: Abnormal | Flag: H (above normal range) | Ref range: 1.8–7.5 x10⁹/L | From: CBC Full Blood Count (03 Mar 2026)
    """
```

Fields exposed: `test_name`, `section`, result value (`normal_result` or `abnormal_result`), `status`, `flag` with human-readable label, `reference_range_low`–`reference_range_high`, `units`, report name, report date.

---

#### Tool 1: `get_all_reports`

```python
@tool
def get_all_reports() -> str:
    """
    Get a summary list of all reports for the patient.
    Use when patient asks 'what reports do I have?' or 'show my reports'.
    """
    reports = db.query(Report)\
        .filter(Report.patient_id == patient_id)\
        .order_by(Report.report_date.desc())\
        .all()

    # Returns lines like:
    # • [5] CBC Full Blood Count — Reported: 03 Mar 2026 | Collected: 01 Mar 2026 | Status: Final | Specimen: Blood
```

**Use when:** Patient wants an overview of all their reports (not the actual test values).

---

#### Tool 2: `get_report_details`

```python
@tool
def get_report_details(report_name: str) -> str:
    """
    Get full test results by report name, section name, OR individual test/analyte name.
    Searches three levels automatically:
      1. Report name     → "CBC", "Lipid Panel", "Full Blood Count"
      2. Section name    → "haematology", "biochemistry", "liver function"
      3. Test/analyte    → "neutrophil", "haemoglobin", "platelet", "glucose"
    """
    # Level 1: match report.report_name ILIKE %report_name%
    # Level 2: match report_description.section ILIKE %report_name%
    # Level 3: match report_description.test_name ILIKE %report_name%
```

**Use when:** Patient asks about any specific report, section, or individual analyte. This is the **primary search tool** — it handles almost every lookup.

---

#### Tool 3: `get_abnormal_results`

```python
@tool
def get_abnormal_results() -> str:
    """
    Get all flagged (H / L / **) results across ALL reports.
    Use when patient asks 'are any results abnormal?', 'what was high?', 'anything critical?'
    """
    flagged = db.query(ReportDescription)\
        .join(Report, Report.id == ReportDescription.report_id)\
        .filter(
            Report.patient_id == patient_id,
            ReportDescription.flag.isnot(None),
            ReportDescription.flag != "",
        )\
        .order_by(Report.report_date.desc())\
        .all()
```

**Use when:** Patient wants to know what's wrong, what's flagged, what to be worried about.

---

#### Tool 4: `get_latest_report`

```python
@tool
def get_latest_report(report_name: str) -> str:
    """
    Get the most recent report of a given type — header info only (date, status, specimen).
    Use when patient asks 'when was my last CBC?' or 'my most recent thyroid test'.
    Note: does NOT return test values — chain with get_report_details if values are needed.
    """
```

---

#### Tool 5: `get_results_by_section`

```python
@tool
def get_results_by_section(section_name: str) -> str:
    """
    Get all results within a specific report section.
    Use only for explicit section queries like 'all my haematology results'.
    Common sections: HAEMATOLOGY, BIOCHEMISTRY, BLOOD BANK, LIPID PROFILE,
                     LIVER FUNCTION, KIDNEY FUNCTION, THYROID, URINE, SEROLOGY
    """
```

**Note:** `get_report_details` already handles section lookups. Use this only if you specifically need ALL results in a section.

---

#### Tool 6: `get_all_report_data`

```python
@tool
def get_all_report_data() -> str:
    """
    Get the COMPLETE lab history — every report with every test result.
    Use for broad requests: 'summarize all my tests', 'complete lab history',
    'how are my results overall?', 'give me an overview of all results'.
    """
    # Fetches all reports then all descriptions for each report
    # Returns a rich multi-section text block with totals
```

---

### 10.2 Bill Tools

**File:** `services/agent/tools/bill_tools.py`

**Models used:** `Bill`, `BillDescription`

#### Shared Formatters

```python
def _bill_header(b: Bill, today: date) -> str:
    """
    Returns:
      Invoice #INV-001 [OVERDUE]
        Invoice date  : 15 Jan 2025
        Due date      : 01 Feb 2025
        Initial amount: ₹5000.00
        Discount      : ₹500.00
        Tax           : ₹250.00
        Total amount  : ₹4750.00
    """

def _bill_line(d: BillDescription) -> str:
    """
    Returns:
      • Consultation — CPT: 99213 | Qty: 1 × ₹800 = ₹800
    """
```

#### Tool 1: `get_all_bills`

Summary list of all bills — invoice number, date, total, due date, overdue flag. Use for "show my bills", "list my invoices".

#### Tool 2: `get_bill_details(invoice_number)`

Full breakdown of one specific invoice including all line items. Must have invoice number first (get it from `get_all_bills` if unknown).

#### Tool 3: `get_total_outstanding`

Grand total of all bills with per-bill breakdown. Use for "how much do I owe in total?".

#### Tool 4: `get_latest_bill`

Most recent invoice with full line items already included. No need to chain with `get_bill_details`.

#### Tool 5: `get_all_bill_data`

Complete billing history — every invoice with every line item plus grand total. Use for comprehensive overviews.

---

### 10.3 Medicine Tools

**File:** `services/agent/tools/medicine_tools.py`

**Models used:** `Medication`, `MedicationSchedule`, `RecurrenceType`, `Doctor`

#### Shared Formatters

```python
def _recurrence_str(rec: RecurrenceType | None) -> str:
    """
    daily → "daily"
    alternate → "every 2 days (starting 01 Jan 2026)"
    cycle → "cyclic — take 5 days, skip 2 days"
    """

def _schedule_str(sched: MedicationSchedule | None) -> str:
    """
    Returns: "Before Breakfast, After Lunch, After Dinner"
    Uses MEAL_SLOTS and SLOT_LABELS from reminder_service
    """

def _med_header(m: Medication, today: date) -> str:
    """
    Returns:
      Medication: Amlodipine [Active]
        Strength      : 5mg
        Form          : Tablet
        Dosage        : 1 tablet
        Frequency     : 1x per day
        Dosing days   : 30
        Days remaining: 14
        Recurrence    : daily
        Schedule      : After Breakfast
        Prescribed by : Dr. Sandra M. Lee
        Prescribed on : 2026-02-15
    """
```

#### Tool 1: `get_all_medications`

All active medications with full detail headers. Joins `Medication`, `MedicationSchedule`, `RecurrenceType`, `Doctor`.

#### Tool 2: `get_medication_schedule`

Each drug mapped to its meal-slot labels. Use for "when do I take my medicines?".

#### Tool 3: `get_medication_details(drug_name)`

Complete profile of one specific drug (partial name match, case-insensitive).

#### Tool 4: `get_last_reminder`

When each medication's last reminder was sent. Reads `MedicationSchedule.latest_notified_at`.

#### Tool 5: `get_next_reminder`

When each medication's next reminder is scheduled. Uses `_compute_next_notify_at` from the reminder service.

#### Tool 6: `get_todays_medications`

What to take today, grouped by meal slot. Filters by `_is_active_today()` logic from reminder service.

#### Tool 7: `get_all_medication_data`

Complete prescription history — active AND inactive medications with full detail. Use for "my complete medication history".

---

### 10.4 Doctor Tools

**File:** `services/agent/tools/doctor_tools.py`

**Models used:** `PatientDoctor`, `Doctor`

#### Shared Formatter

```python
def _doctor_block(doc: Doctor) -> str:
    """
    Returns:
      Doctor: Dr. Sandra M. Lee
        Speciality : Cardiology
        Email      : sandra.lee@hospital.com
        Phone      : +1-555-0123
    """
    # Always shows every field, uses "Not on record" for nulls — never silently omits
```

#### Tool 1: `get_my_doctors`

All doctors assigned to this patient. Queries `PatientDoctor` join `Doctor`. Use for "who is my doctor?", "my healthcare team".

#### Tool 2: `get_doctor_by_name(name)`

Specific doctor by partial name match (case-insensitive). If no match found, the LLM should fall back to `get_my_doctors` and show available options.

#### Tool 3: `get_all_doctor_data`

Complete list of all assigned doctors. Functionally same as `get_my_doctors` but preferred when patient explicitly asks for "complete" or "full" doctor list.

---

## 11. Chat History Service

**File:** `services/agent/chat_history_service.py`

Reads and writes the `chat_history` table to maintain conversation continuity.

```python
def fetch_last_10(patient_id: int, db: Session) -> list[dict]:
    """
    Fetch last 10 turns, ordered oldest → newest (so LLM reads chronologically).

    Output format:
    [
      {"role": "user",      "content": "what are my blood results?"},
      {"role": "assistant", "content": "Your haemoglobin is 14.6..."},
      ...
    ]
    """
    rows = db.query(ChatHistory)\
        .filter(ChatHistory.patient_id == patient_id)\
        .order_by(ChatHistory.timestamp.desc())\
        .limit(10)\
        .all()
    rows.reverse()  # reverse: we fetched newest-first, now make it oldest-first
    # Each DB row stores one user/assistant pair → expand into two dict entries

def save_turn(patient_id: int, user_msg: str, ai_msg: str, db: Session) -> None:
    """Save a completed conversation turn after the graph returns its answer."""
    entry = ChatHistory(patient_id=patient_id, user_msg=user_msg, ai_msg=ai_msg)
    db.add(entry)
    db.commit()
```

Chat history is passed to **every** LLM prompt so the assistant can follow conversations across multiple turns (e.g., "tell me more about that" refers to the previous answer).

---

## 12. API Entry Point — `chat_routes.py`

**File:** `routes/chat_routes.py`

The FastAPI route that receives the HTTP request, runs the graph, and returns the answer.

```python
class ChatRequest(BaseModel):
    patient_id: int      # which patient is asking
    message:    str      # what they said

class ChatResponse(BaseModel):
    patient_id:       int
    user_message:     str
    ai_response:      str
    intents_detected: list[str]   # e.g. ["reports", "medicine"]


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):

    # 1. Validate patient exists and is active
    patient = db.query(Patient).filter(
        Patient.id == req.patient_id,
        Patient.is_active == True,
    ).first()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # 2. Load conversation history
    history = fetch_last_10(req.patient_id, db)

    # 3. Build the initial state dictionary
    initial_state: AgentState = {
        "patient_id":       req.patient_id,
        "user_msg":         req.message.strip(),
        "current_datetime": datetime.now(IST).strftime("%A, %d %b %Y, %I:%M %p IST"),
        "chat_history":     history,
        "intents":          [],
        "pending_intents":  [],
        "node_responses":   {},
        "final_answer":     None,
        "call_counts":      {},
        "total_calls":      0,
        "error":            None,
    }

    # 4. Build the graph (tools bound to this patient + session)
    graph = build_agent_graph(req.patient_id, db)

    # 5. Run the entire graph — blocks until final_answer is set
    result: AgentState = graph.invoke(initial_state)

    # 6. Save this turn to chat history
    save_turn(req.patient_id, req.message, result["final_answer"], db)

    # 7. Return response
    return ChatResponse(
        patient_id=req.patient_id,
        user_message=req.message,
        ai_response=result["final_answer"],
        intents_detected=result["intents"],
    )
```

---

## 13. End-to-End Request Flow

Let's trace a real example: **Patient 3 asks "What are my blood test results and when do I take my medicines?"**

```
POST /api/chat
Body: { "patient_id": 3, "message": "What are my blood test results and when do I take my medicines?" }
```

### Step 1 — HTTP Handler (`chat_routes.py`)
- Validates patient 3 exists and is active ✓
- Fetches last 10 conversation turns from DB
- Builds `initial_state` with `user_msg = "What are my blood test results..."`, `intents = []`, etc.
- Calls `build_agent_graph(3, db)` → creates graph with 21 tools bound to patient 3
- Calls `graph.invoke(initial_state)`

### Step 2 — Graph Entry: `supervisor_router`
- `increment_and_check` → call_counts = `{"supervisor": 1}`, total_calls = 1
- Calls `gpt-oss-120b` with routing prompt + patient's message
- LLM outputs: `{"intents": ["reports", "medicine"]}`
- State updated: `intents = ["reports", "medicine"]`, `pending_intents = ["reports", "medicine"]`
- `route_after_supervisor` sees `pending[0] = "reports"` → routes to `reports_node`

### Step 3 — `reports_node`
- `increment_and_check` → call_counts = `{"supervisor": 1, "reports": 1}`, total_calls = 2
- Builds messages with system prompt + human message containing the patient's question
- **LLM call 1:** `gpt-oss-20b` decides to call `get_all_report_data` (broad overview request)
- Tool executes: `db.query(Report).filter(patient_id=3).all()` → fetches all reports + all test descriptions
- Tool result appended to messages
- **LLM call 2:** LLM now has all the data → generates text response about blood results
- State updated: `node_responses = {"reports": "Your CBC from 03 Mar 2026 shows..."}`, `pending_intents = ["medicine"]`
- Edge → `supervisor_checker`

### Step 4 — `supervisor_checker` (first pass)
- `increment_and_check` → total_calls = 4
- `pending_intents = ["medicine"]` → NOT empty → **Case A** → just passes through
- `route_after_checker` sees `pending[0] = "medicine"` → routes to `medicine_node`

### Step 5 — `medicine_node`
- `increment_and_check` → total_calls = 5
- **LLM call 1:** decides to call `get_medication_schedule` (patient asked "when do I take")
- Tool executes: fetches all active medications with their slot schedules
- **LLM call 2:** generates text response about medication timing
- State updated: `node_responses = {"reports": "...", "medicine": "You are taking Amlodipine 5mg After Breakfast..."}`, `pending_intents = []`
- Edge → `supervisor_checker`

### Step 6 — `supervisor_checker` (second pass)
- `pending_intents = []` → **Case B** → validate completeness
- LLM asked: "Did we answer both the blood test question AND the medicines question?"
- LLM responds: `{"missing": []}` — all covered ✓
- State updated: `pending_intents = []` confirmed

### Step 7 — `supervisor_synthesizer`
- Formats all responses: `"[REPORTS]\nYour CBC...\n\n[MEDICINE]\nYou are taking..."`
- Calls `gpt-oss-120b` with synthesis prompt
- LLM writes one clean patient-friendly response combining both sections
- State updated: `final_answer = "Your most recent CBC shows your haemoglobin at 14.6 g/dL which is within normal range..."`
- Edge → `END`

### Step 8 — Back in HTTP Handler
- `result["final_answer"]` extracted
- Saved to `chat_history` table
- `ChatResponse` returned with `intents_detected = ["reports", "medicine"]`

### Total LLM Calls for This Example
| Node | Calls |
|---|---|
| supervisor_router | 1 |
| reports_node (call tools + answer) | 2 |
| supervisor_checker (pass 1, no LLM) | 0 |
| medicine_node (call tools + answer) | 2 |
| supervisor_checker (pass 2, validate) | 1 |
| supervisor_synthesizer | 1 |
| **Total** | **7** (well under limit of 10) |

---

## 14. File Structure Reference

```
services/
└── agent/
    ├── __init__.py
    ├── state.py                    ← AgentState TypedDict
    ├── guards.py                   ← Loop limits + call counter
    ├── graph.py                    ← Graph assembly and conditional edges
    ├── chat_history_service.py     ← fetch_last_10, save_turn
    │
    ├── nodes/
    │   ├── __init__.py
    │   ├── supervisor.py           ← supervisor_router, supervisor_checker, supervisor_synthesizer
    │   ├── reports_node.py         ← build_reports_node()
    │   ├── bills_node.py           ← build_bills_node()
    │   ├── medicine_node.py        ← build_medicine_node()
    │   └── doctors_node.py         ← build_doctors_node()
    │
    └── tools/
        ├── __init__.py             ← re-exports all build_*_tools functions
        ├── report_tools.py         ← build_report_tools() → 6 tools
        ├── bill_tools.py           ← build_bill_tools()   → 5 tools
        ├── medicine_tools.py       ← build_medicine_tools() → 7 tools
        └── doctor_tools.py         ← build_doctor_tools() → 3 tools

core/
├── llm_init.py                     ← get_supervisor_llm(), get_node_llm()
└── config.py                       ← settings (GROQ_API_KEY, DATABASE_URL, etc.)

routes/
└── chat_routes.py                  ← POST /api/chat endpoint
```

### Quick Tool Count Summary

| Domain | Tools | Key Capability |
|---|---|---|
| Reports | 6 | 3-level search (report → section → analyte), abnormal flags |
| Bills | 5 | Line-item breakdown, overdue detection, grand total |
| Medicine | 7 | Schedule awareness, reminder times, active/inactive history |
| Doctors | 3 | Contact details, partial name search |
| **Total** | **21** | |

### LLM Call Limits Summary

| Limit | Value | Where enforced |
|---|---|---|
| Per-node LLM calls | 3 | `PER_NODE_CALL_LIMIT` in `guards.py`, used in node loops |
| Global LLM calls | 10 | `GLOBAL_CALL_LIMIT` in `guards.py`, checked in every `increment_and_check` |

---

*Documentation generated for the Post-Discharge Medical Assistant LangGraph system.*
