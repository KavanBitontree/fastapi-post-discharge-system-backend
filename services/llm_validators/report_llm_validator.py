"""
report_llm_validator.py
-----------------------
LLM-based extraction and validation of structured data from any lab report PDF.

Design principles:
  - LLM does ALL parsing: handles any format, any lab, any country.
  - Pydantic v2 validators normalize every field after LLM response.
  - validate_extracted_report() filters non-medical content before DB store.
  - No regex anywhere: pure string operations and LLM intelligence.
"""

import json
import logging
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError

from groq import RateLimitError as GroqRateLimitError
from langchain_groq import ChatGroq
from core.config import settings
from core.llm_init import llm

logger = logging.getLogger(__name__)

# Dedicated LLM for report extraction with a high token ceiling.
# The global `llm` (max_tokens=8000) is kept for other validators.
# A 60-test report produces ~14k tokens of JSON — needs headroom.
_REPORT_LLM = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=settings.GROQ_API_KEY,
    temperature=0,
    max_tokens=32768,
)


_CHUNK_SIZE = 40_000

_NON_MEDICAL_NAMES: frozenset = frozenset({
    "name", "patient name", "patient", "date of birth", "dob", "age", "age/sex",
    "sex", "gender", "mrn", "passport", "passport no", "lab no", "labno",
    "lab number", "location", "branch", "consultant", "phone", "telephone",
    "address", "email", "patient id", "patient reference", "test", "result",
    "flag", "unit", "units", "reference range", "reference", "collected",
    "received", "reported", "report date", "collection date", "specimen",
    "specimen type", "order number", "requisition", "page", "pageno",
    "please file", "report completed", "confidential", "version",
    "interpretive data", "classification", "printout", "note",
})

_QUAL_NORMAL: frozenset = frozenset({
    "negative", "non-reactive", "non reactive", "not detected", "absent",
    "nil", "clear", "normal", "not present", "not seen", "none seen",
    "no growth", "no organisms", "undetected", "non detected",
})

_QUAL_ABNORMAL: frozenset = frozenset({
    "positive", "reactive", "detected", "present", "abnormal",
    "growth detected", "organisms present", "inadequate sample",
})


def _extract_number_from_string(s: str) -> Optional[str]:
    """Extract first parseable float from a string like '<14.3'. No regex."""
    if not s:
        return None
    cleaned = s.strip().lstrip("<>=\u2264\u2265()\\ ")
    try:
        float(cleaned)
        return cleaned.strip()
    except ValueError:
        pass
    for token in cleaned.split():
        token = token.strip(".,;:()")
        try:
            float(token)
            return token
        except ValueError:
            continue
    return None


def _parse_range_without_regex(s: str) -> tuple:
    """Parse reference range string into (low, high). No regex."""
    if not s:
        return None, None
    s = s.strip().strip("()")
    s_lower = s.lower()

    if s_lower.startswith(("<", "\u2264", "le ", "<= ")):
        return None, _extract_number_from_string(s)
    if s_lower.startswith((">", "\u2265", "ge ", ">= ")):
        return _extract_number_from_string(s), None

    searchable = s
    for kw in ("fasting:", "fasting :", "male:", "female:", "normal:"):
        idx = s_lower.find(kw)
        if idx != -1:
            searchable = s[idx + len(kw):]
            break

    for sep in (" - ", " \u2013 ", " \u2014 ", "- ", " -", "-"):
        if sep in searchable:
            parts = searchable.split(sep, 1)
            low  = _extract_number_from_string(parts[0])
            high = _extract_number_from_string(parts[1])
            if low and high:
                return low, high

    num = _extract_number_from_string(s)
    if num:
        return None, num
    return None, None


class TestResult(BaseModel):
    """Maps directly to ReportDescription DB model. All fields self-normalize."""

    test_name: str = Field(
        description=(
            "Full name of the test/analyte exactly as written in the report. "
            "Examples: 'Haemoglobin', 'Red Blood Cell', 'TSH (Ultrasensitive)', "
            "'Neutrophils (%)', 'Erythrocyte Sedimentation Rate', 'eGFR (CKD-EPI)'. "
            "Preserve all spaces between words. NEVER merge words. "
            "NEVER include patient demographics as test names."
        )
    )
    section: Optional[str] = Field(
        None,
        description=(
            "Nearest preceding section/category heading. "
            "Examples: 'HAEMATOLOGY', 'RENAL FUNCTION', 'LIPID PROFILE', 'ENDOCRINE', "
            "'LIVER FUNCTION TEST', 'FULL BLOOD COUNT', 'URINE EXAMINATION'. "
            "null if no section heading present."
        )
    )
    normal_result: Optional[str] = Field(
        None,
        description="Result value ONLY when within reference range and no flag. null if flagged."
    )
    abnormal_result: Optional[str] = Field(
        None,
        description="Result value ONLY when outside reference range or flag present. null if normal."
    )
    flag: Optional[str] = Field(
        None,
        description=(
            "Abnormality direction: 'H' (High), 'L' (Low), '**' (Critical). "
            "Normalize: HIGH/HI/above -> 'H'. LOW/LO/below -> 'L'. CRITICAL/PANIC/HH/LL/!! -> '**'. "
            "Single '*': compare value to ref range -> H if result > high, L if result < low. "
            "null when result is within normal range."
        )
    )
    units: Optional[str] = Field(
        None,
        description=(
            "Unit of measurement ONLY: 'g/dL', 'mmol/L', 'x10^9/L', '%', 'U/L'. "
            "NEVER include the reference range here. "
            "Reference range is inside parentheses -> belongs in reference_range_low/high. "
            "null if no unit."
        )
    )
    reference_range_low: Optional[str] = Field(
        None,
        description=(
            "Lower bound of reference range as a plain number string. "
            "'( 13.0- 18.0)' -> '13.0'. '(<14.3)' -> null. '(>90)' -> '90'. "
            "'(Fasting:3.9-6.0)' -> '3.9'. null when no lower bound. "
            "NEVER include units or parentheses."
        )
    )
    reference_range_high: Optional[str] = Field(
        None,
        description=(
            "Upper bound of reference range as a plain number string. "
            "'( 13.0- 18.0)' -> '18.0'. '(<14.3)' -> '14.3'. '(>90)' -> null. "
            "null when no upper bound. NEVER include units or parentheses."
        )
    )

    @field_validator("test_name", mode="before")
    @classmethod
    def _clean_test_name(cls, v):
        if not v:
            raise ValueError("test_name is required")
        return str(v).strip()

    @field_validator("section", mode="before")
    @classmethod
    def _clean_section(cls, v):
        if not v:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("normal_result", "abnormal_result", mode="before")
    @classmethod
    def _clean_result(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("flag", mode="before")
    @classmethod
    def _normalize_flag(cls, v):
        if not v:
            return None
        f = str(v).strip().upper()
        if f in ("H", "HIGH", "HI", "ABOVE NORMAL", "ABOVE"):
            return "H"
        if f in ("L", "LOW", "LO", "BELOW NORMAL", "BELOW"):
            return "L"
        if f in ("**", "HH", "LL", "CRITICAL", "PANIC", "CRIT", "!!", "ALERT"):
            return "**"
        if f in ("*", "ABNORMAL", "A"):
            return "*"
        return None

    @field_validator("units", mode="before")
    @classmethod
    def _clean_units(cls, v):
        if not v:
            return None
        s = str(v).strip()
        for ch in ("(", "<", ">"):
            idx = s.find(ch)
            if idx != -1:
                s = s[:idx].strip()
        return s if s else None

    @field_validator("reference_range_low", "reference_range_high", mode="before")
    @classmethod
    def _clean_range_bound(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        try:
            float(s)
            return s
        except ValueError:
            pass
        return _extract_number_from_string(s)

    @model_validator(mode="after")
    def _resolve_result_and_flag(self) -> "TestResult":
        combined = self.normal_result or self.abnormal_result
        if not combined:
            return self

        result_lower = combined.lower().strip()

        if result_lower in _QUAL_NORMAL:
            self.normal_result   = combined
            self.abnormal_result = None
            self.flag            = None
            return self

        if result_lower in _QUAL_ABNORMAL:
            self.abnormal_result = combined
            self.normal_result   = None
            self.flag            = self.flag or "**"
            return self

        if self.flag in ("H", "L", "**"):
            if self.normal_result and not self.abnormal_result:
                self.abnormal_result = self.normal_result
                self.normal_result   = None
            return self

        if self.flag == "*":
            try:
                val      = float(combined.replace(",", ".").strip())
                resolved = False

                if self.reference_range_high:
                    try:
                        high = float(str(self.reference_range_high).strip())
                        if val > high:
                            self.flag            = "H"
                            self.abnormal_result = combined
                            self.normal_result   = None
                            resolved             = True
                    except ValueError:
                        pass

                if not resolved and self.reference_range_low:
                    try:
                        low = float(str(self.reference_range_low).strip())
                        if val < low:
                            self.flag            = "L"
                            self.abnormal_result = combined
                            self.normal_result   = None
                            resolved             = True
                    except ValueError:
                        pass

                if not resolved:
                    self.flag            = None
                    self.normal_result   = combined
                    self.abnormal_result = None

            except (ValueError, TypeError):
                self.flag            = None
                self.normal_result   = combined
                self.abnormal_result = None

        return self


class ReportHeader(BaseModel):
    """Maps directly to Report DB model."""

    report_name: str = Field(
        description=(
            "Primary title of the report. "
            "Examples: 'Premier Wellness Package', 'Complete Blood Count (CBC)', "
            "'Lipid Profile', 'Thyroid Function Test', 'Liver Function Test'. "
            "For multi-panel reports use the overarching name. "
            "NEVER null: infer from test content if no explicit title is present."
        )
    )
    patient_email: Optional[str] = Field(
        None,
        description="Patient email if present (must contain '@'). null if not found."
    )
    report_date: Optional[str] = Field(
        None,
        description=(
            "Report generation date in ISO 8601 format. "
            "'Reported :29/10/2021 21:26' -> '2021-10-29T21:26:00'. null if not found."
        )
    )
    collection_date: Optional[str] = Field(
        None,
        description=(
            "Specimen collection date in ISO 8601 format. "
            "'Collected:29/10/2021 11:00' -> '2021-10-29T11:00:00'. null if not found."
        )
    )
    received_date: Optional[str] = Field(
        None,
        description=(
            "Specimen received date in ISO 8601 format. "
            "'Received :29/10/2021 15:07' -> '2021-10-29T15:07:00'. null if not found."
        )
    )
    specimen_type: Optional[str] = Field(
        None,
        description="Specimen type e.g. 'Whole Blood', 'Serum', 'Urine'. null if not found."
    )
    status: Optional[str] = Field(
        None,
        description="Report status e.g. 'FINAL', 'ROUTINE'. null if not found."
    )

    @field_validator("report_name", mode="before")
    @classmethod
    def _clean_report_name(cls, v):
        if not v:
            return "Unknown Report"
        s = str(v).strip()
        return s if s else "Unknown Report"


class ExtractedReport(BaseModel):
    """Complete extracted report: maps to Report + ReportDescription models."""
    header:       ReportHeader
    test_results: List[TestResult]


def validate_extracted_report(extracted: ExtractedReport) -> ExtractedReport:
    """
    Filter and deduplicate test results extracted by the LLM.

    Removes:
      - Demographic / metadata entries (Name, DOB, MRN, etc.)
      - Entries with no result value at all
      - Entries whose test_name has no alphabetic characters
      - Single-character test names
      - Duplicate (test_name, units) pairs: keeps first occurrence
    """
    medical_tests: List[TestResult] = []
    seen: set = set()

    for t in extracted.test_results:
        name_lower = t.test_name.lower().strip()

        if name_lower in _NON_MEDICAL_NAMES:
            continue
        if not t.normal_result and not t.abnormal_result:
            continue
        if not any(c.isalpha() for c in t.test_name):
            continue
        if len(t.test_name.strip()) < 2:
            continue

        dedup_key = (name_lower, (t.units or "").lower().strip())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        medical_tests.append(t)

    return ExtractedReport(header=extracted.header, test_results=medical_tests)


_SYSTEM_PROMPT = """You are a world-class medical laboratory report data extraction engine.

You receive text from a PDF lab report. Format varies by lab:
  - Columnar layouts with pipe separators (TEST | RESULT | FLAG | UNIT | REF RANGE)
  - Tabular layouts with spaces between columns
  - Single-line compact formats
  - Multi-page reports (--- PAGE BREAK --- marks page boundaries, NOT stop signals)
  - Any lab worldwide: Pantai, Quest, LabCorp, NHS, government labs, private clinics

Your task: extract EVERY test result as structured JSON. Never summarize, skip, or fabricate.

REQUIRED JSON SCHEMA
====================
{
  "header": {
    "report_name": "string (required, never null)",
    "patient_email": "string or null",
    "report_date": "ISO 8601 string or null  e.g. '2021-10-29T21:26:00'",
    "collection_date": "ISO 8601 string or null",
    "received_date": "ISO 8601 string or null",
    "specimen_type": "string or null",
    "status": "string or null"
  },
  "test_results": [
    {
      "test_name": "string (required)",
      "section": "string or null",
      "normal_result": "string or null",
      "abnormal_result": "string or null",
      "flag": "null or 'H' or 'L' or '**'",
      "units": "string or null",
      "reference_range_low": "numeric string or null",
      "reference_range_high": "numeric string or null"
    }
  ]
}

FIELD RULES
===========

UNITS vs REFERENCE RANGE (most common mistake):
  Line: "Haemoglobin  14.6  g/dL  ( 13.0- 18.0)"
    units                = "g/dL"
    reference_range_low  = "13.0"
    reference_range_high = "18.0"
  NEVER put the parenthesised range inside units.

REFERENCE RANGE FORMATS:
  "( 13.0- 18.0)"          -> low="13.0"  high="18.0"
  "(<14.3)"                 -> low=null    high="14.3"
  "(>90)"                   -> low="90"    high=null
  "(1.005-1.030)"           -> low="1.005" high="1.030"
  "(Fasting : 3.9 - 6.0)"  -> low="3.9"   high="6.0"
  Provide ONLY the numeric string: no units, no parentheses.

NORMAL vs ABNORMAL:
  Flag present  -> abnormal_result = value, normal_result = null
  No flag       -> normal_result   = value, abnormal_result = null

FLAG NORMALIZATION:
  H  -> HIGH, High, H, HI, above normal
  L  -> LOW, Low, L, LO, below normal
  ** -> HH, LL, CRITICAL, PANIC, !!
  *  -> single asterisk: compare result to ref range -> H if result > high, L if result < low

QUALITATIVE RESULTS:
  "Negative", "Non-Reactive", "Not Detected", "Nil", "Clear", "No Growth"
    -> normal_result = value, flag = null
  "Positive", "Reactive", "Detected", "Present"
    -> abnormal_result = value, flag = "**"
  Blood group -> normal_result = value, flag = null

SECTIONS: Use nearest preceding ALL-CAPS heading. Never use patient/lab names.

MULTI-UNIT TESTS (HbA1c in % AND mmol/mol): emit TWO entries.

HORMONE MULTI-RANGE TESTS: use only the range applicable to this patient.

CALCULATED VALUES INCLUDE:
  Albumin-Globulin Ratio, Cholesterol/HDL Ratio, eGFR (CKD-EPI), Non-HDL-Cholesterol.

IGNORE COMPLETELY:
  - Patient demographics: Name, DOB, Age, Sex, MRN, Passport, Address
  - Lab/hospital name, consultant, branch, phone, location
  - Footer text, confidentiality notices
  - Column headers (TEST, RESULT, FLAG, UNIT, REFERENCE RANGE)
  - Page numbers, PAGE BREAK markers
  - Interpretation/classification tables
  - Notes, disclaimers, specimen codes

TEST NAME PRESERVATION: "Red Blood Cell" NOT "RedBloodCell"

OUTPUT CONTRACT:
  Return ONLY valid JSON matching the schema above. No preamble, explanation, or markdown fences.
  Every field present (null for missing optionals).
  Process ALL pages. Never stop at page break.
  Never hallucinate values not in the text.
"""


def extract_with_llm(raw_text: str) -> ExtractedReport:
    """Extract structured report data from raw PDF text using LLM."""
    if len(raw_text) <= _CHUNK_SIZE:
        return _extract_single(raw_text)
    return _extract_chunked(raw_text)


def extract_report_name_fallback(raw_text: str) -> str:
    """Lightweight fallback: extract just the report name when main extraction fails."""
    prompt = (
        "Return ONLY the report title from this lab report text. "
        "Examples: 'Complete Blood Count (CBC)', 'Lipid Profile'. "
        "If unknown, return 'Unknown Report'. No other text.\n\n"
        f"{raw_text[:3000]}"
    )
    response = llm.invoke(prompt)
    return response.content.strip() or "Unknown Report"


# ---------------------------------------------------------------------------
# Internal extraction helpers
# ---------------------------------------------------------------------------

# _JSON_MODE_LLM kept for potential structured-output path if needed.
_JSON_MODE_LLM = None


def _get_json_mode_llm():
    global _JSON_MODE_LLM
    if _JSON_MODE_LLM is None:
        _JSON_MODE_LLM = _REPORT_LLM.with_structured_output(ExtractedReport, method="json_mode")
    return _JSON_MODE_LLM


def _parse_raw_json(raw: str) -> ExtractedReport:
    """
    Parse raw JSON string into ExtractedReport.
    Strips markdown fences the LLM may accidentally add.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            ln for ln in lines
            if not ln.strip().startswith("```")
        ).strip()
    data = json.loads(text)
    return ExtractedReport.model_validate(data)


def _extract_single(text: str, is_continuation: bool = False) -> ExtractedReport:
    """
    Single LLM call using _REPORT_LLM (max_tokens=32768, temperature=0).

    Uses direct llm.invoke() — no with_structured_output wrapper.
    This avoids ALL Groq tool-call and json_mode size restrictions.
    The response is parsed manually into ExtractedReport via Pydantic.

    Falls back to json_mode structured output if plain parse fails.
    """
    if is_continuation:
        user_prompt = (
            "Extract ALL test results from this continuation of a lab report.\n"
            "Header already captured. Focus only on test results.\n"
            "Return JSON with the same schema: {\"header\": {...}, \"test_results\": [...]}.\n\n"
            f"CONTINUATION:\n{text}"
        )
    else:
        user_prompt = (
            "Extract all structured data from this medical laboratory report.\n"
            "Apply all rules. Extract EVERY test result. Process all pages.\n\n"
            f"REPORT TEXT:\n{text}"
        )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]

    # Attempt 1: plain invoke + manual parse (no middleware, no size cap from wrappers)
    try:
        response = _REPORT_LLM.invoke(messages)
        result = _parse_raw_json(response.content)
        if result and result.test_results:
            return result
        logger.warning("Plain invoke returned empty test_results; trying json_mode")
    except GroqRateLimitError:
        raise  # propagate immediately — no point retrying on rate limit
    except (json.JSONDecodeError, ValidationError, Exception) as e:
        logger.warning("Plain invoke/parse failed (%s); trying json_mode fallback", e)

    # Attempt 2: json_mode structured output
    structured_llm = _get_json_mode_llm()
    return structured_llm.invoke(messages)


def _extract_chunked(raw_text: str) -> ExtractedReport:
    """Split long reports into chunks, extract each, merge results."""
    chunks = [raw_text[i:i + _CHUNK_SIZE] for i in range(0, len(raw_text), _CHUNK_SIZE)]

    first     = _extract_single(chunks[0], is_continuation=False)
    all_tests = list(first.test_results)

    for i, chunk in enumerate(chunks[1:], start=2):
        logger.info("Processing chunk %d/%d", i, len(chunks))
        try:
            part = _extract_single(chunk, is_continuation=True)
            all_tests.extend(part.test_results)
        except Exception as e:
            logger.warning("Chunk %d extraction failed (%s); skipping", i, e)

    return ExtractedReport(header=first.header, test_results=all_tests)
