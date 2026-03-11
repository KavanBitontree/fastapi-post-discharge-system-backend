import math
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from pinecone import Pinecone


def get_index(index_name: str, api_key: str):
    pc = Pinecone(api_key=api_key)
    return pc.Index(index_name)


def embed_text(model: Any, text: str) -> List[float]:
    return model.encode(text, normalize_embeddings=True).tolist()


def embed_texts(model: Any, texts: List[str]) -> List[List[float]]:
    # batch encode = faster + consistent normalization
    return model.encode(texts, normalize_embeddings=True).tolist()


def pinecone_query(
    *,
    index,
    namespace: str,
    vector: List[float],
    top_k: int = 12,
    where: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    kwargs = {
        "vector": vector,
        "top_k": top_k,
        "namespace": namespace,
        "include_metadata": True,
    }
    if where:
        kwargs["filter"] = where

    res = index.query(**kwargs)
    matches = res.get("matches", []) if isinstance(res, dict) else getattr(res, "matches", [])
    out = []
    for m in matches:
        mid = m["id"] if isinstance(m, dict) else m.id
        score = m["score"] if isinstance(m, dict) else m.score
        meta = m.get("metadata", {}) if isinstance(m, dict) else (m.metadata or {})
        out.append({"id": mid, "score": float(score), "metadata": meta})
    return out


def _norm_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _lexical_score(query: str, title: str) -> float:
    """
    Lightweight lexical signal (no extra deps):
    - token overlap (Jaccard-ish)
    - sequence similarity
    Returns 0..1
    """
    q = _norm_text(query)
    t = _norm_text(title)
    if not q or not t:
        return 0.0

    q_tokens = set(q.split())
    t_tokens = set(t.split())
    if not q_tokens or not t_tokens:
        tok = 0.0
    else:
        inter = len(q_tokens & t_tokens)
        tok = inter / max(1, min(len(q_tokens), len(t_tokens)))

    seq = SequenceMatcher(a=q, b=t).ratio()

    # cap + blend
    return max(0.0, min(1.0, 0.55 * tok + 0.45 * seq))


def _rrf_fuse(results_per_query: List[List[Dict[str, Any]]], k: int = 60) -> Dict[str, float]:
    """
    Reciprocal Rank Fusion: robust across multiple query phrasings.
    Returns code->rrf_score
    """
    scores: Dict[str, float] = {}
    for rlist in results_per_query:
        for rank, item in enumerate(rlist, start=1):
            code = item["id"]
            scores[code] = scores.get(code, 0.0) + 1.0 / (k + rank)
    return scores


def retrieve_candidates_for_problem(
    *,
    index,
    namespace: str,
    embed_model: Any,
    problem: str,
    queries: List[str],
    top_k_per_query: int = 16,
    max_candidates_per_problem: int = 40,
    where: Optional[Dict[str, Any]] = None,
    lexical_weight: float = 0.25,
) -> List[Dict[str, Any]]:
    """
    Better retrieval than single-query:
    - Run each planned query
    - Fuse via RRF (stable)
    - Re-rank with a small lexical match boost against candidate titles
    """
    queries = [q for q in queries if (q or "").strip()]
    if not queries:
        return []

    vectors = embed_texts(embed_model, queries)
    results_per_query: List[List[Dict[str, Any]]] = []
    raw_by_code: Dict[str, Dict[str, Any]] = {}

    for q, v in zip(queries, vectors):
        hits = pinecone_query(
            index=index,
            namespace=namespace,
            vector=v,
            top_k=top_k_per_query,
            where=where,
        )
        results_per_query.append(hits)
        for h in hits:
            code = h["id"]
            if code not in raw_by_code:
                raw_by_code[code] = h

    rrf = _rrf_fuse(results_per_query, k=60)

    # build combined score
    scored: List[Dict[str, Any]] = []
    for code, base_rrf in rrf.items():
        h = raw_by_code.get(code, {"id": code, "score": 0.0, "metadata": {}})
        md = h.get("metadata") or {}
        title = ""
        if isinstance(md, dict):
            title = md.get("title", "") or ""
        # lexical boost: best across query variants
        lex = 0.0
        for q in queries:
            lex = max(lex, _lexical_score(q, title))
        final = (1.0 - lexical_weight) * base_rrf + lexical_weight * lex

        scored.append(
            {
                "id": code,
                "score": float(final),
                "metadata": md,
                "title": title,
                "problem": problem,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_candidates_per_problem]


def merge_candidates(
    results_by_problem: List[Tuple[str, List[Dict[str, Any]]]]
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """
    Keeps your original behavior :contentReference[oaicite:4]{index=4}:
    - Dedupes by ICD code
    - score = max across problems
    - tracks problems per code
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    merged: Dict[str, Dict[str, Any]] = {}

    for problem, matches in results_by_problem:
        grouped[problem] = matches
        for m in matches:
            code = m["id"]
            if code not in merged:
                merged[code] = {
                    "code": code,
                    "score": m["score"],
                    "title": (m.get("metadata") or {}).get("title", ""),
                    "metadata": m.get("metadata") or {},
                    "problems": set([problem]),
                }
            else:
                merged[code]["score"] = max(merged[code]["score"], m["score"])
                merged[code]["problems"].add(problem)
                if not merged[code]["title"]:
                    merged[code]["title"] = (m.get("metadata") or {}).get("title", "")

    merged_list = list(merged.values())
    for item in merged_list:
        item["problems"] = sorted(list(item["problems"]))

    merged_list.sort(key=lambda x: x["score"], reverse=True)
    return merged_list, grouped


def retrieve_all_candidates(
    *,
    planned_problems: List[Dict[str, Any]],
    index,
    namespace: str,
    embed_model: Any,
    top_k_per_query: int = 16,
    max_candidates_per_problem: int = 40,
    where: Optional[Dict[str, Any]] = None,
    lexical_weight: float = 0.25,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    """
    Returns:
      merged_candidates (global)
      grouped_by_problem (for UI)
      candidates_by_problem (BEST for selector to avoid cross-problem contamination)
    """
    results_by_problem: List[Tuple[str, List[Dict[str, Any]]]] = []
    candidates_by_problem: Dict[str, List[Dict[str, Any]]] = {}

    for p in planned_problems:
        prob = (p.get("problem") or "").strip()
        queries = p.get("queries") or []
        if not prob or not isinstance(queries, list) or not queries:
            continue

        cands = retrieve_candidates_for_problem(
            index=index,
            namespace=namespace,
            embed_model=embed_model,
            problem=prob,
            queries=queries,
            top_k_per_query=top_k_per_query,
            max_candidates_per_problem=max_candidates_per_problem,
            where=where,
            lexical_weight=lexical_weight,
        )
        candidates_by_problem[prob] = cands
        results_by_problem.append((prob, cands))

    merged, grouped = merge_candidates(results_by_problem)
    return merged, grouped, candidates_by_problem