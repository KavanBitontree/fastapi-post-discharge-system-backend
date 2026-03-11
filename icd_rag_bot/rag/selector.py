import json
from typing import Any, Dict, List, Optional, Set, Tuple
import re
from icd_rag_bot.rag.openrouter_client import chat_completion


SELECTOR_SYSTEM = """You are an ICD-10-CM coding assistant.

You will be given:
1) A clinical note
2) Extracted problems
3) Candidate ICD-10-CM codes (titles + metadata) from retrieval

Task:
- For EACH problem, select the best code(s) using ONLY the provided candidates.
- Do NOT invent codes not in candidates.
- Prefer the MOST specific code supported by the note and candidate title.
- Keep output stable, minimal, and evidence-based.

SPECIFICITY HIERARCHY -- apply in this strict order:
  1. Most specific combination code covering co-existing conditions (if in candidates)
  2. Most specific single code fully supported by the note
  3. "Other specified" code (titles containing "other" or ending in patterns like .09, .89, .x9)
     when the condition is documented but the exact sub-type is not named in the note
  4. "Unspecified" code only as last resort when the note truly lacks the required detail
- NEVER select both a parent code and its child code for the same condition.
- NEVER select an "unspecified" code when a more specific candidate is supported by the note.
- "Other specified" codes are MORE SPECIFIC than "unspecified" codes: when a candidate has
  "other" in its title (e.g., "Other primary hyperaldosteronism") and another has "unspecified"
  (e.g., "Hyperaldosteronism, unspecified"), always prefer the "other specified" candidate if
  the note confirms the broader condition category without naming a specific sub-type.

PARENT CODE PROHIBITION:
- A code is a PARENT of another when its value is a strict alphanumeric prefix of the other
  (e.g., E26.0 is a parent of E26.09; I12 is a parent of I12.9).
- When candidates for the same problem include BOTH a parent code AND one or more child codes,
  ALWAYS select the child code. NEVER select a parent/category code when a more specific
  child is available in the candidate list.
- This applies regardless of how well the parent code seems to match -- the child is always
  the correct choice over its parent.

NAMED DISEASE vs RESIDUAL CATEGORY:
- ICD-10-CM has two types of "other" codes:
  (a) Specific named disease codes with a precise title (e.g., "Homocystinuria", "Conn syndrome")
  (b) Residual catch-all codes with generic titles (e.g., "Other disorders of X metabolism",
      "Other specified Y")
- When candidates contain BOTH a code with a SPECIFIC NAMED DISEASE TITLE and a code with a
  GENERIC RESIDUAL TITLE for the same clinical problem, prefer the specific named disease code
  if the note's condition matches or is consistent with that specific name.
- TERMINOLOGY MISMATCH RULE: The clinical term in the note may differ from the ICD-10-CM title
  for the exact same condition. ICD-10-CM often uses the disease/enzyme disorder name while
  clinical practice uses a measurement-based name. Common pattern:
    Clinical "-emia" term (elevated metabolite)  <->  ICD "-uria" disease title
    e.g., "hyperhomocysteinemia" (clinical) = "Homocystinuria" (ICD title for E72.11)
  When a specific named disease code and a residual "Other disorders of X" code are both
  candidates, ask: could the named disease title be the same underlying condition as the
  documented term, just expressed differently? If yes, ALWAYS select the specific named
  disease code, not the residual catch-all.
- Only select the residual/catch-all code when no specific named code in the candidates
  matches the documented condition even accounting for terminology differences.

DIAGNOSIS CODE vs FINDING/SYMPTOM CODE -- STRICT OVERRIDE:
- When candidates contain BOTH an R-chapter code (findings/symptoms) AND a disease-chapter
  code (chapters A-Q, S-T) that covers the same clinical condition: ALWAYS select the
  disease-chapter code and DISCARD the R-chapter code. No exceptions.
- More broadly: diagnosis-level codes (body-system chapters A-Q, S-T) are always preferred
  over symptom, finding, or abnormal-result codes (R-chapter, certain Z-codes) whenever the
  underlying condition is documented or clearly supported by the clinical note.
- Select a symptom or finding code ONLY when:
  * No diagnosis code in the candidate list covers the documented condition, OR
  * The note explicitly states the finding is incidental, unexplained, or under active investigation.

MISSING DOCUMENTATION -- handle consistently:
- When required detail is absent (stage, laterality, type, acuity):
  * Select the "unspecified" or "not otherwise specified" candidate.
  * Add a short note: "[missing detail] not documented".
  * Do NOT guess or infer the missing detail.
- Use "Needs clarification" only when NO candidate in the list matches the condition at all.

COMBINATION AND ETIOLOGY-MANIFESTATION CODING:
- When a problem involves a primary disease causing a secondary manifestation, first check
  candidates for a combination code covering both. If one exists, prefer it.
- When no combination code is in candidates, select individual codes for the primary condition
  AND the manifestation, and note the etiology-manifestation relationship.
- Assign multiple codes per problem ONLY when clinically and coding-rule justified.

DUPLICATE PREVENTION:
- The same code must never appear more than once across all problems.
- Do NOT select codes representing the same concept at different specificity levels.

Return STRICT JSON only:
{
  "results": [
    {
      "problem": "string",
      "selected_codes": [
        {"code": "string", "title": "string", "rationale": "short evidence-based reason"}
      ],
      "notes": "optional short note"
    }
  ]
}
"""


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned


def _safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = _strip_code_fences(text)

    # Attempt 1: parse as-is
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract outermost { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start: end + 1])
        except json.JSONDecodeError:
            pass

    # Attempt 3: truncation recovery — the LLM was cut off mid-JSON.
    # Salvage any complete result objects that were emitted before the cutoff.
    # A complete result block ends with ...}  (closing the result item dict).
    # We collect all fully-parseable objects from the "results" array.
    salvaged: List[Dict[str, Any]] = []
    # Find each candidate result object: starts with {"problem" and ends with }
    for m in re.finditer(r'\{[^{}]*"problem"[^{}]*\}', cleaned, re.DOTALL):
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict) and obj.get("problem"):
                salvaged.append(obj)
        except json.JSONDecodeError:
            pass
    if salvaged:
        return {"results": salvaged}

    # Nothing recoverable — return empty so the caller can degrade gracefully
    return {"results": []}


def _is_unspecified_title(title: str) -> bool:
    t = (title or "").lower()
    return "unspecified" in t or "unspec" in t


def _drop_ancestors_and_unspecified(selected: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Your existing cleanup logic :contentReference[oaicite:5]{index=5}, kept and tightened.
    """
    if not selected:
        return selected

    codes = [s.get("code", "").strip() for s in selected if s.get("code")]
    titles = {s.get("code", "").strip(): (s.get("title", "") or "") for s in selected}

    def category(c: str) -> str:
        return c.split(".")[0].strip()

    drop = set()

    # Drop ancestor codes by prefix relationship
    for c in codes:
        for o in codes:
            if c == o:
                continue
            if o.startswith(c) and len(o) > len(c):
                drop.add(c)

    # Drop unspecified when a more specific in same category exists
    for c in codes:
        if _is_unspecified_title(titles.get(c, "")):
            cat = category(c)
            if any(
                (o != c) and (category(o) == cat) and (not _is_unspecified_title(titles.get(o, "")))
                for o in codes
            ):
                drop.add(c)

    return [s for s in selected if (s.get("code", "").strip() not in drop)]


def _limit_codes_per_problem(selected: List[Dict[str, str]], max_codes_per_problem: int) -> List[Dict[str, str]]:
    if max_codes_per_problem <= 0:
        return []
    return selected[:max_codes_per_problem]


def _global_dedupe(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    New: de-duplicate the SAME code across problems to avoid overcoding.
    Keep the first occurrence; remove later duplicates and add a short note.
    """
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []

    for r in results:
        codes = r.get("selected_codes") or []
        if not isinstance(codes, list):
            out.append(r)
            continue

        kept = []
        dropped = []
        for c in codes:
            code = (c.get("code") or "").strip()
            if not code:
                continue
            if code in seen:
                dropped.append(code)
            else:
                seen.add(code)
                kept.append(c)

        if dropped:
            note = (r.get("notes") or "").strip()
            extra = f"duplicate code removed across problems: {', '.join(dropped)}"
            r["notes"] = (note + ("; " if note else "") + extra).strip()

        r["selected_codes"] = kept
        out.append(r)

    return out


def select_codes(
    *,
    note: str,
    planned_problems: List[Dict[str, Any]],
    merged_candidates: List[Dict[str, Any]],
    openrouter_api_key: str,
    model: str,
    max_codes_per_problem: int = 2,
    candidates_by_problem: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    Key upgrades vs your current selector :contentReference[oaicite:6]{index=6}:
    - Uses candidates_by_problem (strongly recommended) to prevent cross-problem contamination.
    - Lower default max_codes_per_problem (less overcoding, more stability).
    - Global dedupe across problems + deterministic cleanup.
    """

    def to_candidate_rows(cands: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        out_rows: List[Dict[str, Any]] = []
        for c in cands[:limit]:
            md = c.get("metadata") or {}
            code = c.get("code") or c.get("id") or ""
            title = c.get("title", "") or (md.get("title", "") if isinstance(md, dict) else "")
            out_rows.append(
                {
                    "code": code,
                    "title": title,
                    "score": round(float(c.get("score", 0.0)), 6),
                    "parent_code": md.get("parent_code", "") if isinstance(md, dict) else "",
                    "level": md.get("level", None) if isinstance(md, dict) else None,
                    "problems": c.get("problems", []),
                }
            )
        return [r for r in out_rows if r.get("code")]

    if candidates_by_problem:
        payload_candidates: Dict[str, List[Dict[str, Any]]] = {}
        for p in planned_problems:
            prob = (p.get("problem") or "").strip()
            if not prob:
                continue
            cands = candidates_by_problem.get(prob, [])
            payload_candidates[prob] = to_candidate_rows(cands, limit=min(len(cands), 60))

        user_payload = {
            "note": note,
            "max_codes_per_problem": max_codes_per_problem,
            "planned_problems": planned_problems,
            "candidates_by_problem": payload_candidates,
        }
    else:
        # fallback to merged
        top_candidates = merged_candidates[:80]
        user_payload = {
            "note": note,
            "max_codes_per_problem": max_codes_per_problem,
            "planned_problems": planned_problems,
            "candidates": to_candidate_rows(top_candidates, limit=80),
        }

    text = chat_completion(
        model=model,
        api_key=openrouter_api_key,
        messages=[
            {"role": "system", "content": SELECTOR_SYSTEM},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=2500,
    )

    data = _safe_json_loads(text)
    results = data.get("results", [])
    cleaned_results: List[Dict[str, Any]] = []

    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue

        problem = (item.get("problem") or "").strip()
        selected_codes = item.get("selected_codes") or []
        notes = (item.get("notes") or "").strip()

        # "Needs clarification" handling
        if isinstance(selected_codes, str) and selected_codes.lower().strip() == "needs clarification":
            cleaned_results.append({"problem": problem, "selected_codes": [], "notes": notes or "Needs clarification"})
            continue

        if not isinstance(selected_codes, list):
            selected_codes = []

        norm = []
        for s in selected_codes:
            if not isinstance(s, dict):
                continue
            code = (s.get("code") or "").strip()
            title = (s.get("title") or "").strip()
            rationale = (s.get("rationale") or "").strip()
            if code:
                norm.append({"code": code, "title": title, "rationale": rationale})

        norm = _drop_ancestors_and_unspecified(norm)
        norm = _limit_codes_per_problem(norm, max_codes_per_problem)

        cleaned_results.append({"problem": problem, "selected_codes": norm, "notes": notes})

    cleaned_results = _global_dedupe(cleaned_results)
    return {"results": cleaned_results}