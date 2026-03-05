"""
LLM Initialization for LangGraph
Uses Groq for fast inference with llama-3.3-70b-versatile
"""
 
from langchain_groq import ChatGroq
from core.config import settings
 
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=settings.GROQ_API_KEY,
    temperature=0.3,
)