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
)