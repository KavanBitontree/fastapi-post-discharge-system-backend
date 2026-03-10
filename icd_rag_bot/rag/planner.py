import json
import re
from typing import Any, Dict, List, Tuple

from icd_rag_bot.rag.openrouter_client import chat_completion


PLANNER_SYSTEM = """You are a clinical query planner for ICD-10-CM retrieval.

You will receive a structured clinical lab/investigation report and output STRICT JSON
with a de-duplicated list of coding-relevant clinical problems.

The report is structured as:
  INVESTIGATIONS       -- list of report names, dates, specimen types
  ABNORMAL RESULTS     -- flagged findings (HIGH / LOW / CRITICAL / ABNORMAL). Use these for coding.
  NORMAL/WITHIN-RANGE  -- context only; do not generate problems from these unless unique.

OUTPUT FORMAT (STRICT):
{
  "problems": [
    {
      "problem": "string",
      "confidence": "high|medium|low",
      "queries": ["string", "..."]
    }
  ]
}

CORE RULES:
- Output JSON only. No markdown. No commentary.
- Do NOT invent diagnoses not supported by the report.
- Derive problems primarily from the ABNORMAL RESULTS section.
- Prefer the clinical diagnosis name over a description of the measurement.
- Keep the MOST specific concept only -- no duplicates at different specificity levels.
- Stable ordering:
  1) Primary diagnoses (directly named or clearly supported by abnormal results)
  2) Complications and manifestations of primary diagnoses in other organs
  3) Co-morbid conditions supported by abnormal results
  4) Isolated abnormal findings only when no diagnosis name can be concluded

DIAGNOSIS ELEVATION:
- Each abnormal result is a clue to an underlying condition -- not simply a reading.
- For each flagged result ask: what named clinical condition does this value support?
  Generate a problem using THAT CONDITION NAME, not the measurement name.
  Examples of the principle (applies to ANY condition, not just these):
    HIGH creatinine + LOW eGFR        -> problem: chronic kidney disease
    HIGH aldosterone or LOW renin     -> problem: primary hyperaldosteronism
    HIGH cholesterol + HIGH LDL       -> problem: hyperlipidemia or mixed dyslipidemia
    HIGH homocysteine                 -> problem: hyperhomocysteinemia
    HIGH CRP or elevated ESR          -> problem: elevated inflammatory marker
    HIGH or CRITICAL blood pressure   -> problem: hypertension
    HIGH glucose + HIGH HbA1c         -> problem: diabetes mellitus
    LOW hemoglobin + LOW hematocrit   -> problem: anemia
- Only generate a measurement-descriptor problem when no clinical diagnosis can be
  concluded from the value and its clinical context.

COMBINATION CONDITIONS AND MULTI-ORGAN INVOLVEMENT:
- When ABNORMAL RESULTS contains flagged values from two or more different organ
  systems or sections, identify whether a single primary condition drives that
  multi-organ pattern. If yes:
  (a) Generate the primary condition as a standalone problem
  (b) Generate one problem per primary-condition plus each affected-organ combination
  (c) Generate each component condition as its own standalone problem
- Multi-organ pattern signals: simultaneous abnormal values across cardiovascular (BP),
  renal (creatinine, eGFR, protein), metabolic (lipids, glucose), endocrine (hormones),
  haematological, or other cross-system combinations.
- Also apply when a primary diagnosis directly causes a manifestation in another organ:
  generate both as separate problems plus a combined problem.

INDEPENDENT CONDITIONS -- no implicit causation:
- When the report shows abnormal results suggesting two DIFFERENT named conditions
  (e.g., elevated BP suggesting hypertension AND elevated hormone suggesting an endocrine
  disorder), treat them as SEPARATE independent problems UNLESS the note EXPLICITLY states
  a causal link using words like "caused by", "secondary to", "due to".
- Do NOT synthesise a "secondary" or "due to" combination just because two conditions
  co-exist or are plausibly related. Absent an explicit statement, code each independently.
- This applies to any combination: cardiovascular + endocrine, renal + metabolic, etc.

MANIFESTATION QUERIES:
- When a condition is a downstream manifestation of another condition (e.g., proteinuria
  or nephropathy in a patient with hypertension or CKD; retinopathy in diabetes; neuropathy
  in diabetes), generate the manifestation as its own problem AND include a query that
  contains the phrase "in diseases classified elsewhere" -- this is how ICD-10-CM titles
  etiology-manifestation codes (e.g., N08, H36) that will not surface otherwise.
  Example: problem "proteinuria in hypertension" -> queries should include
  "glomerular disorder in diseases classified elsewhere",
  "nephropathy in diseases classified elsewhere"

QUERY CONSTRUCTION -- CRITICAL:
- Queries are sent as literal text to a vector database of ICD-10-CM code TITLES.
  The exact words determine which codes surface. Right words = right codes.
- PRIMARY RULE: Write the DISEASE or DISORDER name -- never the measurement description.
    Correct: essential hypertension, chronic kidney disease stage 3, primary hyperaldosteronism
    Wrong:   elevated blood pressure, high creatinine, abnormal aldosterone level
- Build a specificity ladder per problem using 2-4 queries:
  * Query 1: most specific disease name plus key modifier (subtype, organ, acuity if known)
  * Query 2: disease name combined with affected organ or system
  * Query 3: always include one query with the word "other" prepended or appended to the
    disease name -- this retrieves ICD-10-CM "other specified" codes (.09, .89 endings)
    which represent the correct code when a subtype is present but not further specified
  * Query 4 (optional): broader synonym or unspecified fallback for the same disease
- All queries: lowercase; no punctuation; no ICD codes; 2-20 words each
- For conditions where detail is not documented (stage, laterality, subtype):
  * Do NOT guess the missing detail
  * Add one query ending in unspecified or not otherwise specified

CONFIDENCE:
- high: named diagnosis stated clearly or directly concluded from the report
- medium: clearly supported by one or more flagged abnormal results
- low: indirect or weak inference only

Return JSON now.
"""


_CONF_SET = {"high", "medium", "low"}


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return t


def _normalize_query(q: str) -> str:
    q = (q or "").strip().lower()
    # remove punctuation -> spaces
    q = re.sub(r"[^a-z0-9\s]", " ", q)
    # collapse whitespace
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def plan_queries(
    *,
    note: str,
    openrouter_api_key: str,
    model: str,
) -> List[Dict[str, Any]]:
    user_msg = f"""Clinical note:
{note}

Return STRICT JSON now."""
    text = chat_completion(
        model=model,
        api_key=openrouter_api_key,
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=1500,
    )

    cleaned = _strip_code_fences(text)

    # Attempt 1: parse as-is
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Attempt 2: extract outermost { ... } in case of surrounding text
        s = cleaned.find("{")
        e = cleaned.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                data = json.loads(cleaned[s: e + 1])
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

    problems = data.get("problems", [])
    if not isinstance(problems, list):
        return []

    # Cross-problem dedupe (queries MUST NOT repeat across problems) :contentReference[oaicite:3]{index=3}
    used_queries = set()
    out: List[Dict[str, Any]] = []

    for p in problems:
        if not isinstance(p, dict):
            continue

        prob = (p.get("problem") or "").strip()
        conf = (p.get("confidence") or "medium").strip().lower()
        if conf not in _CONF_SET:
            conf = "medium"

        queries = p.get("queries") or []
        if not prob or not isinstance(queries, list):
            continue

        norm_qs = []
        for q in queries:
            nq = _normalize_query(str(q))
            if not nq:
                continue
            if nq in used_queries:
                continue
            norm_qs.append(nq)

        norm_qs = _dedupe_preserve_order(norm_qs)

        # Keep minimal but strong recall
        if prob and norm_qs:
            for q in norm_qs:
                used_queries.add(q)
            out.append({"problem": prob, "confidence": conf, "queries": norm_qs[:4]})

    return out