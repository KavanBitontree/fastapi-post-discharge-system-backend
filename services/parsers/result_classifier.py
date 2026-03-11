"""
result_classifier.py
--------------------
Post-parse abnormality classifier for medical test results.

The LLM is responsible only for extracting raw values from the PDF.
This module handles the deterministic step of classifying each result
as normal or abnormal — no LLM involvement needed for this logic.

Classification pipeline (in order)
------------------------------------
1. Normalise the raw flag string from the PDF:
   - "within normal range" markers (—, -, WNL, N …)  → flag = None
   - known abnormal markers (H, L, *, **, HH, LL …)  → canonical form
2. If a canonical abnormal flag is present (from step 1 OR from LLM),
   ensure the value is in abnormal_result (move from normal_result if needed).
3. If no flag was found, compare the numeric value against the reference
   range bounds and auto-assign H / L as appropriate.
4. If nothing applies (non-numeric, no bounds), leave the result untouched.
"""

from __future__ import annotations

import re
from typing import Optional

from schemas.report_schemas import TestResult, ValidatedReport


# ── Flag vocabulary ────────────────────────────────────────────────────────────

# Flags that explicitly mean "within normal range" — normalise to None
_NORMAL_FLAG_VALUES: set[str] = {
    "—", "-", "–",          # various dashes / em-dashes
    "wnl",                   # Within Normal Limits
    "n", "nr", "nl",         # Normal / Normal Range / Normal Level
    "within normal range",
    "within normal limits",
    "normal",
}

# Canonical mapping for known abnormal flag strings
_ABNORMAL_FLAG_CANON: dict[str, str] = {
    "h":        "H",
    "hh":       "H",        # double-high / panic high
    "high":     "H",
    "l":        "L",
    "ll":       "L",        # double-low / panic low
    "low":      "L",
    "*":        "*",
    "**":       "**",       # critical / panic value
    "***":      "**",
    "c":        "**",       # Critical
    "crit":     "**",
    "critical": "**",
    "a":        "*",        # Abnormal (generic)
    "abnormal": "*",
}


def _normalise_flag(raw: Optional[str]) -> Optional[str]:
    """
    Convert a raw flag string from the PDF into a canonical value.

    Returns:
        None            → value is within normal range (or no flag)
        "H"             → abnormally high
        "L"             → abnormally low
        "**"            → critical / panic value
        "*"             → generic abnormal
        original string → unrecognised flag — preserved as-is
    """
    if not raw:
        return None
    stripped = raw.strip()
    lower = stripped.lower()

    if lower in _NORMAL_FLAG_VALUES:
        return None                     # explicitly normal

    canon = _ABNORMAL_FLAG_CANON.get(lower)
    if canon:
        return canon

    # Preserve unrecognised flags (lab-specific codes etc.)
    return stripped


def _parse_numeric(value: Optional[str]) -> Optional[float]:
    """
    Extract the first numeric token from a string.

    Handles values like "12.5", "< 5.0", "> 100", "120 H", "3,200".
    Returns None if no number can be extracted.
    """
    if not value:
        return None
    cleaned = value.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


def classify_test_result(result: TestResult) -> TestResult:
    """
    Classify a single TestResult as normal or abnormal.

    Steps
    -----
    1. Normalise the raw flag (handles —, **, HH, LL, WNL, etc.).
    2. If a canonical abnormal flag exists, ensure the value lives in
       abnormal_result (moves it from normal_result if the LLM put it there).
    3. If no flag, do numeric comparison against the reference range.
    4. If no comparison is possible, leave the result unchanged.
    """
    # ── Step 1: normalise the flag string from the PDF ────────────────────────
    canonical_flag = _normalise_flag(result.flag)

    # ── Step 2: explicit abnormal flag found (PDF or LLM-detected) ───────────
    # Covers H, L, *, **, and any unrecognised lab-specific flag kept as-is
    # Also covers the case where LLM set abnormal_result directly
    has_explicit_abnormal = (
        result.abnormal_result          # LLM already moved value to abnormal_result
        or (canonical_flag is not None  # PDF had an explicit abnormal flag
            and canonical_flag not in ("", ))
    )

    if has_explicit_abnormal:
        # Value might be in normal_result (LLM set flag but forgot to move it)
        value_str = result.abnormal_result or result.normal_result
        if not value_str:
            # Flag present but no value at all — just normalise the flag
            return result.model_copy(update={"flag": canonical_flag})
        return result.model_copy(update={
            "abnormal_result": value_str,
            "normal_result":   None,
            "flag":            canonical_flag,
        })

    # ── Step 3: no explicit flag — numeric comparison against reference range ──
    raw_value = result.normal_result
    if not raw_value:
        return result.model_copy(update={"flag": None})  # clear any stale "—"

    has_low  = bool(result.reference_range_low)
    has_high = bool(result.reference_range_high)
    if not has_low and not has_high:
        # No bounds to compare against — leave value in normal_result, clear flag
        return result.model_copy(update={"flag": None})

    value = _parse_numeric(raw_value)
    if value is None:
        # Non-numeric result (e.g. "Positive", "Reactive") — can't compare
        return result.model_copy(update={"flag": None})

    low  = _parse_numeric(result.reference_range_low)  if has_low  else None
    high = _parse_numeric(result.reference_range_high) if has_high else None

    if high is not None and value > high:
        return result.model_copy(update={
            "abnormal_result": raw_value,
            "normal_result":   None,
            "flag":            "H",
        })

    if low is not None and value < low:
        return result.model_copy(update={
            "abnormal_result": raw_value,
            "normal_result":   None,
            "flag":            "L",
        })

    # ── Step 4: within range ──────────────────────────────────────────────────
    return result.model_copy(update={"flag": None})


def classify_report_results(report: ValidatedReport) -> ValidatedReport:
    """
    Run the classifier over every test result in a ValidatedReport.

    Returns a new ValidatedReport with updated test_results.
    Normal/abnormal classification is done purely in Python — no LLM call.
    """
    classified = [classify_test_result(r) for r in report.test_results]

    flagged = sum(1 for r in classified if r.abnormal_result)
    print(
        f"[classifier] {len(classified)} tests processed — "
        f"{flagged} abnormal, {len(classified) - flagged} normal"
    )

    return report.model_copy(update={"test_results": classified})

