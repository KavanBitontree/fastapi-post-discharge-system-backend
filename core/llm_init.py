"""
LLM Initialization for LangGraph
Uses Groq for fast inference with gpt-oss-120b
"""

from langchain_groq import ChatGroq
from core.config import settings

# Model configuration
MODEL_NAME = "openai/gpt-oss-120b"

llm = ChatGroq(
    model=MODEL_NAME,
    api_key=settings.GROQ_API_KEY,
    temperature=0.3,
    max_tokens=8000,
)

# ─────────────────── Model names ───────────────────────
SUPERVISOR_MODEL = "openai/gpt-oss-120b"   
NODE_MODEL       = "openai/gpt-oss-20b"

_GROQ_COMMON = dict(
    api_key=settings.GROQ_API_KEY,
    max_tokens=4096,
)


def get_supervisor_llm() -> ChatGroq:
    """Returns the Supervisor LLM (heavyweight router + synthesizer)."""
    return ChatGroq(model=SUPERVISOR_MODEL, temperature=0.2, **_GROQ_COMMON)


def get_node_llm() -> ChatGroq:
    """Returns the specialist node LLM (reports / bills / medicine)."""
    return ChatGroq(model=NODE_MODEL, temperature=0.1, **_GROQ_COMMON)