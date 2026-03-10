"""
routes/icd_routes.py
---------------------
ICD-10-CM code lookup via RAG pipeline.

GET  /icd/info    → pipeline configuration info
POST /icd/lookup  → clinical note → best ICD-10-CM codes

Pipeline:
  1. plan_queries  — LLM extracts clinical problems + search queries
  2. retrieve_all_candidates — multi-query Pinecone search + RRF fusion + lexical rerank
  3. select_codes  — LLM picks the best codes from candidates
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/icd", tags=["ICD-10 RAG"])

# ── Lazy singletons (loaded once on first request) ────────────────────────────

_embedder = None
_pinecone_index = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading SentenceTransformer 'all-MiniLM-L6-v2'...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("SentenceTransformer loaded.")
    return _embedder


def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is None:
        from icd_rag_bot.rag.retriever import get_index
        logger.info("Connecting to Pinecone index '%s'...", settings.PINECONE_INDEX_NAME)
        _pinecone_index = get_index(settings.PINECONE_INDEX_NAME, settings.PINECONE_API_KEY)
        logger.info("Pinecone index connected.")
    return _pinecone_index


# ── Schemas ───────────────────────────────────────────────────────────────────

class ICDLookupRequest(BaseModel):
    note: str = Field(..., min_length=10, description="Clinical note to extract ICD-10-CM codes from")
    top_k_per_query: int = Field(default=40, ge=3, le=50, description="Top K Pinecone results per planned query")
    max_candidates_per_problem: int = Field(default=30, ge=5, le=50, description="Max candidates kept per problem after reranking")
    max_codes_per_problem: int = Field(default=3, ge=1, le=5, description="Max ICD codes the LLM may select per problem")
    lexical_weight: float = Field(default=0.35, ge=0.0, le=0.6, description="Weight of lexical score in final reranking (0 = pure vector)")


class ICDCode(BaseModel):
    code: str
    title: str
    rationale: str


class ICDProblemResult(BaseModel):
    problem: str
    selected_codes: List[ICDCode]
    notes: Optional[str] = None


class ICDLookupResponse(BaseModel):
    results: List[ICDProblemResult]


class ICDInfoResponse(BaseModel):
    index_name: str
    namespace: str
    embedding_model: str
    llm_model: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/info", response_model=ICDInfoResponse, summary="ICD RAG pipeline configuration")
def icd_info():
    """Returns the current ICD-10 RAG pipeline configuration (index, model, namespace)."""
    return ICDInfoResponse(
        index_name=settings.PINECONE_INDEX_NAME,
        namespace=settings.PINECONE_NAMESPACE,
        embedding_model="all-MiniLM-L6-v2",
        llm_model=settings.OPENROUTER_MODEL,
    )


@router.post("/lookup", response_model=ICDLookupResponse, summary="Look up ICD-10-CM codes from a clinical note")
def icd_lookup(req: ICDLookupRequest):
    """
    Given a clinical note, returns the best matching ICD-10-CM codes.

    **Pipeline:**
    1. LLM plans the clinical problems + search queries
    2. Multi-query Pinecone vector search with RRF fusion + lexical rerank
    3. LLM selects the best codes from retrieved candidates
    """
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not configured")
    if not settings.PINECONE_API_KEY:
        raise HTTPException(status_code=503, detail="PINECONE_API_KEY is not configured")

    try:
        from icd_rag_bot.rag.planner import plan_queries
        from icd_rag_bot.rag.retriever import retrieve_all_candidates
        from icd_rag_bot.rag.selector import select_codes

        embedder = _get_embedder()
        index = _get_pinecone_index()

        # Step 1: plan problems & search queries from clinical note
        planned = plan_queries(
            note=req.note,
            openrouter_api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
        )

        # Step 2: retrieve candidates from Pinecone
        merged, grouped, candidates_by_problem = retrieve_all_candidates(
            planned_problems=planned,
            index=index,
            namespace=settings.PINECONE_NAMESPACE,
            embed_model=embedder,
            top_k_per_query=req.top_k_per_query,
            max_candidates_per_problem=req.max_candidates_per_problem,
            where=None,
            lexical_weight=req.lexical_weight,
        )

        # Step 3: LLM selects best codes
        selected: Dict[str, Any] = select_codes(
            note=req.note,
            planned_problems=planned,
            merged_candidates=merged,
            candidates_by_problem=candidates_by_problem,
            openrouter_api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
            max_codes_per_problem=req.max_codes_per_problem,
        )

        return selected

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ICD lookup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"ICD lookup failed: {str(exc)}")
