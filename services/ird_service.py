"""
services/ird_service.py
------------------------
Insurance Ready Document (IRD) Generator.

Pipeline
--------
1. Fetch discharge + patient + reports (with descriptions) + bills + medications from DB
2. Format report descriptions into a structured clinical note
3. Call ICD-10 RAG pipeline in-process (reuses loaded embedder + Pinecone index)
4. Call Groq LLM (2 calls) to align findings -> ICD evidence and bill -> findings
5. Generate PDF using ReportLab (Python-native, no system binaries needed)
6. Upload PDF buffer to Cloudinary -> ird_documents/ folder
7. Return result dict

Layout (sections in order)
---------------------------
  1. Header bar
  2. Patient Information (4-column compact grid)
  3. ICD-10 Diagnosis Codes (table: Code | Title | Rationale)
  4. Clinical Evidence Trail (inline narrative per ICD code:
       each code -> supporting test results -> why -> billed CPT items)
  5. Billing Summary (category-grouped CPT table with subtotals + grand total)
  6. Medical Reports & Documents (named hyperlinks)
  7. Bills & Invoices (named hyperlinks)
  8. Footer

Removed vs previous version
-----------------------------
  - DISCHARGE MEDICATIONS & CLINICAL RATIONALE  (removed per spec)
  - DISCHARGE SUMMARY link section              (removed per spec)

Schema facts:
  reports            : id, discharge_id, report_name, report_date, specimen_type,
                       status, report_url
  report_descriptions: test_name, section, normal_result, abnormal_result,
                       flag, units, reference_range_low, reference_range_high
  bills              : id, discharge_id, invoice_number, invoice_date, total_amount, bill_url
  bill_description   : bill_id, cpt_code, description, qty, unit_price, total_price
  medications        : discharge_id, drug_name, dosage, strength, form_of_medicine,
                       frequency_of_dose_per_day, dosing_days, is_active, prescription_date
  medication_schedules: medication_id, before_breakfast/after_breakfast/before_lunch/
                        after_lunch/before_dinner/after_dinner
  discharge_history  : id, patient_id, discharge_date, discharge_summary_url, insurance_ready_url
  patients           : full_name, dob, gender
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from core.config import settings
from models.bill import Bill
from models.discharge_history import DischargeHistory
from models.medication import Medication
from models.patient import Patient
from models.report import Report

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Kolkata")


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _expand_flag(flag: str) -> str:
    """Map raw DB flag abbreviations to unambiguous clinical words."""
    f = (flag or "").strip().upper()
    mapping = {
        "H":   "HIGH",
        "HH":  "CRITICAL HIGH",
        "L":   "LOW",
        "LL":  "CRITICAL LOW",
        "A":   "ABNORMAL",
        "**":  "CRITICAL",
        "C":   "CRITICAL",
        "POS": "POSITIVE",
        "NEG": "NEGATIVE",
        "REF": "REFERRED",
    }
    return mapping.get(f, f) or "ABNORMAL"


def _safe_text(text: str) -> str:
    """Replace characters outside Latin-1 so ReportLab built-in fonts render cleanly."""
    if not text:
        return ""
    replacements = {
        "\u2014": "-",  "\u2013": "-",
        "\u2019": "'",  "\u2018": "'",
        "\u201c": '"',  "\u201d": '"',
        "\u2022": "*",  "\u25aa": "-",  "\u25a0": "-",
        "\u2192": "->", "\u2190": "<-",
        "\u2265": ">=", "\u2264": "<=",
        "\u00b5": "u",  "\u00d7": "x",
        "\u00b1": "+/-",
        "\u2122": "",   "\u00ae": "",
    }
    for ch, repl in replacements.items():
        text = text.replace(ch, repl)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _safe_json_loads(text: str) -> Any:
    """Strip markdown fences then parse JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _trunc(s: str, n: int = 52) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "..."


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Build clinical note from report descriptions
# ─────────────────────────────────────────────────────────────────────────────

def _format_reports_to_clinical_text(reports: List[Report]) -> str:
    """
    Converts Report rows + ReportDescription children into a structured clinical
    note designed for the ICD-10 RAG planner.
    """
    investigation_lines: List[str] = []
    for rpt in reports:
        line = rpt.report_name or "Unknown Report"
        if rpt.report_date:
            line += f" | Date: {rpt.report_date.strftime('%Y-%m-%d')}"
        if rpt.specimen_type:
            line += f" | Specimen: {rpt.specimen_type}"
        if rpt.status:
            line += f" | Status: {rpt.status}"
        investigation_lines.append(f"- {line}")

    investigations = "\n".join(investigation_lines) or "- No investigation records."

    abnormal_lines: List[str] = []
    normal_lines:   List[str] = []

    for rpt in reports:
        report_label = rpt.report_name or "Report"
        for desc in rpt.descriptions or []:
            raw_flag = (desc.flag or "").strip()
            result   = desc.abnormal_result or desc.normal_result or "N/A"

            line = f"  {desc.test_name}: {result}"
            if desc.units:
                line += f" {desc.units}"
            if desc.reference_range_low and desc.reference_range_high:
                line += f" (ref: {desc.reference_range_low}-{desc.reference_range_high})"
            if desc.section:
                line += f" | section: {desc.section}"
            line += f" | report: {report_label}"

            if raw_flag:
                flag_word = _expand_flag(raw_flag)
                line = f"  {desc.test_name}: {result}"
                if desc.units:
                    line += f" {desc.units}"
                line += f" -- {flag_word}"
                if desc.reference_range_low and desc.reference_range_high:
                    line += f" (ref: {desc.reference_range_low}-{desc.reference_range_high})"
                if desc.section:
                    line += f" | section: {desc.section}"
                line += f" | report: {report_label}"
                abnormal_lines.append(line)
            else:
                normal_lines.append(line)

    abnormal_block = (
        "ABNORMAL RESULTS (clinically significant -- use for ICD-10 coding)\n"
        + ("\n".join(abnormal_lines) if abnormal_lines else "  None")
    )
    normal_block = (
        "NORMAL / WITHIN-RANGE RESULTS (context only)\n"
        + ("\n".join(normal_lines) if normal_lines else "  None")
    )

    return (
        f"INVESTIGATIONS\n{investigations}\n\n"
        f"{abnormal_block}\n\n"
        f"{normal_block}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — ICD-10 RAG lookup
# ─────────────────────────────────────────────────────────────────────────────

def _call_icd_lookup_llm_fallback(clinical_note: str) -> List[Dict[str, str]]:
    """
    Direct Groq LLM ICD-10 coding — used when the RAG pipeline is unavailable.
    Returns list of {"code": str, "title": str, "rationale": str}.
    Raises on any failure so the caller can decide how to handle it.
    """
    import requests as _http

    prompt = (
        "You are a certified medical coder (CPC). Based on the clinical findings and lab results "
        "below, assign the most appropriate ICD-10-CM diagnosis codes.\n\n"
        f"{clinical_note}\n\n"
        "Return a JSON array. Each element must follow this exact schema:\n"
        '{"code": str, "title": str, "rationale": str}\n\n'
        "Rules:\n"
        "- Provide 3-8 codes covering all primary diagnoses evidenced by ABNORMAL findings\n"
        "- Use the most specific ICD-10-CM code available (e.g. E11.65, not just E11)\n"
        "- rationale: one sentence citing the specific test name + value that supports the code\n"
        "- Only include codes with clear evidence in the provided findings\n"
        "Respond ONLY with a valid compact JSON array — no markdown, no explanation."
    )
    r = _http.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": "You are a certified medical coder. Respond only with valid JSON."},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens": 2000,
        },
        timeout=60,
    )
    r.raise_for_status()
    data = _safe_json_loads(r.json()["choices"][0]["message"]["content"])
    codes: List[Dict[str, str]] = []
    items = data if isinstance(data, list) else (data.get("codes") or data.get("icd_codes") or [])
    for item in items:
        code = (item.get("code") or "").strip()
        if code:
            codes.append({
                "code":      code,
                "title":     item.get("title", ""),
                "rationale": item.get("rationale", ""),
            })
    return codes


def _call_icd_lookup(clinical_note: str) -> Tuple[List[Dict[str, str]], bool]:
    """
    Runs the ICD-10 RAG pipeline directly in-process.
    If RAG fails for any reason, falls back to direct Groq LLM coding.
    Returns (icd_codes, icd_generation_failed).
    icd_codes: list of {"code": str, "title": str, "rationale": str}
    """
    # ── Primary: Pinecone RAG + OpenRouter ───────────────────────────────────
    try:
        from icd_rag_bot.rag.planner import plan_queries
        from icd_rag_bot.rag.retriever import retrieve_all_candidates
        from icd_rag_bot.rag.selector import select_codes
        from routes.icd_routes import _get_embedder, _get_pinecone_index

        embedder = _get_embedder()
        index    = _get_pinecone_index()

        planned = plan_queries(
            note=clinical_note,
            openrouter_api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
        )
        merged, grouped, candidates_by_problem = retrieve_all_candidates(
            planned_problems=planned,
            index=index,
            namespace=settings.PINECONE_NAMESPACE,
            embed_model=embedder,
            top_k_per_query=50,
            max_candidates_per_problem=35,
            where=None,
            lexical_weight=0.25,
        )
        selected = select_codes(
            note=clinical_note,
            planned_problems=planned,
            merged_candidates=merged,
            candidates_by_problem=candidates_by_problem,
            openrouter_api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
            max_codes_per_problem=3,
        )

        codes: List[Dict[str, str]] = []
        for result in selected.get("results", []):
            for item in result.get("selected_codes", []):
                code = (item.get("code") or "").strip()
                if code:
                    codes.append({
                        "code":      code,
                        "title":     item.get("title", ""),
                        "rationale": item.get("rationale", ""),
                    })

        if codes:
            logger.info("IRD: RAG returned %d ICD codes", len(codes))
            return codes, False

        # RAG returned 0 codes — try LLM fallback before giving up
        logger.warning("IRD: RAG pipeline succeeded but returned 0 codes; trying LLM fallback")

    except Exception as exc:
        logger.warning(
            "ICD-10 RAG lookup failed (%s); trying direct LLM fallback", exc
        )

    # ── Fallback: direct Groq LLM coding ────────────────────────────────────
    try:
        codes = _call_icd_lookup_llm_fallback(clinical_note)
        if codes:
            logger.info("IRD: LLM fallback returned %d ICD codes", len(codes))
            return codes, False
        logger.error("IRD: LLM fallback returned 0 codes")
    except Exception as fb_exc:
        logger.error("ICD-10 LLM fallback also failed: %s", fb_exc, exc_info=True)

    return [], True


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — LLM alignment (2 calls)
# ─────────────────────────────────────────────────────────────────────────────

def _build_abnormal_findings(reports: List[Report]) -> List[Dict]:
    """Extract only flagged findings from report descriptions for LLM prompts."""
    findings = []
    for rpt in reports:
        for desc in rpt.descriptions or []:
            if desc.flag and desc.flag.strip():
                findings.append({
                    "test_name": desc.test_name or "",
                    "result":    desc.abnormal_result or desc.normal_result or "N/A",
                    "flag":      _expand_flag(desc.flag),
                    "units":     desc.units or "",
                    "ref_range": (
                        f"{desc.reference_range_low}-{desc.reference_range_high}"
                        if desc.reference_range_low and desc.reference_range_high
                        else ""
                    ),
                    "report":   rpt.report_name or "Unknown",
                    "section":  desc.section or "",
                })
    return findings


def _build_medications_payload(meds: List[Medication]) -> List[Dict]:
    """
    Snapshot ORM Medication objects into plain dicts while DB session is open.
    Prevents detached-instance errors. Result stored in return dict only.
    """
    payload = []
    for med in meds:
        sched = med.schedule
        parts: List[str] = []
        if sched:
            if sched.before_breakfast: parts.append("Before Breakfast")
            if sched.after_breakfast:  parts.append("After Breakfast")
            if sched.before_lunch:     parts.append("Before Lunch")
            if sched.after_lunch:      parts.append("After Lunch")
            if sched.before_dinner:    parts.append("Before Dinner")
            if sched.after_dinner:     parts.append("After Dinner")

        schedule_str     = ", ".join(parts) if parts else "As directed"
        freq             = med.frequency_of_dose_per_day or 1
        days             = med.dosing_days
        schedule_summary = f"{schedule_str} x{freq}/day"
        if days:
            schedule_summary += f" for {days} days"

        payload.append({
            "drug_name":         med.drug_name or "",
            "dosage":            med.dosage or "",
            "strength":          med.strength or "",
            "form":              med.form_of_medicine.value if med.form_of_medicine else "",
            "schedule_summary":  schedule_summary,
            "prescription_date": str(med.prescription_date) if med.prescription_date else "",
        })

    logger.info("IRD: snapshotted %d medications into payload", len(payload))
    return payload


def _call_llm_alignment(
    icd_codes: List[Dict],
    reports: List[Report],
    bills: List[Bill],
) -> Dict[str, List]:
    """
    3 sequential Groq API calls:
      Call 1 — per ICD code: which test findings support it + clinical reason
      Call 2 — non-drug bill line items (procedures/tests) -> linked test finding
      Call 3 — drug/medication bill line items -> which test result clinically
                justifies prescribing that drug

    Returns:
        {
          "evidence_by_icd":    [...],
          "bill_report_links":  [...],   # procedures/tests
          "drug_finding_links": [...],   # medications -> test finding
        }
    Never raises — returns empty lists on any failure.
    """
    import requests as _http
    import time as _time

    GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
    GROQ_MODEL = "openai/gpt-oss-120b"
    SYSTEM = (
        "You are a clinical pharmacist and medical billing expert preparing an Insurance Ready "
        "Document (IRD). Your job is to link medications and procedures to the test results that "
        "clinically justify them. Be specific: name the exact test and result value. "
        "Respond ONLY with valid compact JSON -- no markdown, no explanation, no preamble."
    )
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    def _post(prompt: str, max_tokens: int = 4000) -> Any:
        r = _http.post(
            GROQ_URL,
            headers=headers,
            json={
                "model":      GROQ_MODEL,
                "messages":   [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        r.raise_for_status()
        return _safe_json_loads(r.json()["choices"][0]["message"]["content"])

    def _to_list(data: Any, key: str) -> List:
        if isinstance(data, dict):
            return data.get(key) or []
        if isinstance(data, list):
            return data
        return []

    # Build full all-findings list (flagged + normal) for drug linking —
    # a drug may be justified by a normal result too (e.g. maintenance therapy)
    all_findings_for_drugs = []
    for rpt in reports:
        for desc in rpt.descriptions or []:
            result = desc.abnormal_result or desc.normal_result or "N/A"
            all_findings_for_drugs.append({
                "test_name": desc.test_name or "",
                "result":    result,
                "flag":      _expand_flag(desc.flag) if desc.flag and desc.flag.strip() else "NORMAL",
                "units":     desc.units or "",
                "ref_range": (
                    f"{desc.reference_range_low}-{desc.reference_range_high}"
                    if desc.reference_range_low and desc.reference_range_high
                    else ""
                ),
                "report":    rpt.report_name or "Unknown",
            })

    abnormal_findings = _build_abnormal_findings(reports)
    icd_json          = json.dumps(icd_codes)
    findings_json     = json.dumps(abnormal_findings)

    # Separate bill items: drugs vs procedures
    drug_forms_kw = {"tablet", "capsule", "injection", "syrup", "solution", "cream",
                     "patch", "inhaler", "suppository", "drops", "gel", "vial",
                     "ampoule", "sachet", "powder", "lotion", "mg ", "mcg ", "iu "}
    drug_bill_items: List[Dict] = []
    proc_bill_items: List[Dict] = []
    for bill in bills:
        for desc in (bill.descriptions or []):
            row = {
                "cpt_code":    (desc.cpt_code or ""),
                "description": (desc.description or ""),
                "qty":         desc.qty,
                "total_price": float(desc.total_price or 0),
            }
            desc_lower = (desc.description or "").lower()
            if any(kw in desc_lower for kw in drug_forms_kw):
                drug_bill_items.append(row)
            else:
                proc_bill_items.append(row)

    # ── Call 1: Per ICD code — supporting findings and clinical reason ─────────
    evidence_by_icd: List = []
    try:
        data1 = _post(
            "Given these ICD-10 diagnosis codes:\n"
            f"{icd_json}\n\n"
            "And these abnormal test findings from medical reports:\n"
            f"{findings_json}\n\n"
            'Return a JSON array named "evidence_by_icd". '
            "Each element represents ONE ICD code and must appear for EVERY code given:\n"
            '{"icd_code":str,"icd_title":str,'
            '"findings":[{"test_name":str,"result":str,"units":str,"flag":str,"reason":str}],'
            '"clinical_summary":str}\n'
            "clinical_summary = one sentence why this code applies to this patient. "
            "If no findings directly link, use empty findings array and explain in clinical_summary. "
            "Include ALL input ICD codes."
        )
        evidence_by_icd = _to_list(data1, "evidence_by_icd")
        logger.info("IRD LLM Call 1: evidence for %d ICD codes", len(evidence_by_icd))
    except Exception as exc:
        logger.warning("IRD LLM Call 1 (evidence_by_icd) failed: %s", exc)

    _time.sleep(1)

    # ── Call 2: Non-drug bill line items -> linked test finding ────────────────
    bill_report_links: List = []
    if proc_bill_items:
        try:
            data2 = _post(
                "Given these procedure / service bill line items:\n"
                f"{json.dumps(proc_bill_items)}\n\n"
                "And these abnormal test findings:\n"
                f"{findings_json}\n\n"
                'Return a JSON array named "bill_report_links". Each element:\n'
                '{"cpt_code":str,"description":str,"total_amount":str,'
                '"linked_finding":str|null,"linked_report":str|null}\n'
                "linked_finding = the specific test name and result value that made this procedure "
                "necessary (e.g. 'HbA1c: 9.2% HIGH'). "
                "Set to null when no clear clinical link exists."
            )
            bill_report_links = _to_list(data2, "bill_report_links")
            logger.info("IRD LLM Call 2: %d bill_report_links", len(bill_report_links))
        except Exception as exc:
            logger.warning("IRD LLM Call 2 (proc->finding) failed: %s", exc)

    _time.sleep(1)

    # ── Call 3: Drug bill items -> which test result clinically justifies them ─
    # This is the key call that fills the empty Linked Finding for medications.
    drug_finding_links: List = []
    if drug_bill_items:
        try:
            data3 = _post(
                "You are reviewing discharge prescriptions for insurance justification.\n\n"
                "These medications were dispensed and billed:\n"
                f"{json.dumps(drug_bill_items)}\n\n"
                "These are ALL the test results available for this patient:\n"
                f"{json.dumps(all_findings_for_drugs)}\n\n"
                "These are the ICD-10 diagnoses assigned:\n"
                f"{icd_json}\n\n"
                'Return a JSON array named "drug_finding_links". Each element covers ONE drug:\n'
                '{"description":str, "linked_finding":str, "linked_report":str, "icd_code":str}\n'
                "CRITICAL: 'description' MUST be copied EXACTLY character-for-character "
                "from the input medication list — never paraphrase, abbreviate, or alter it.\n"
                "linked_finding = the SPECIFIC test name + result value from the patient results "
                "above that most directly justifies prescribing this drug "
                "(e.g. 'HbA1c: 9.2% HIGH', 'Fasting Glucose: 340 mg/dL HIGH', "
                "'TSH: 8.4 mIU/L HIGH', 'eGFR: 58 mL/min LOW'). "
                "linked_report = name of the report that test came from. "
                "icd_code = the single ICD code this drug most directly treats. "
                "Every drug MUST have a linked_finding — use the most relevant test "
                "even if the link is indirect. Never return null for linked_finding. "
                "Return exactly one entry per input drug (same count as the input list)."
            )
            drug_finding_links = _to_list(data3, "drug_finding_links")
            logger.info("IRD LLM Call 3: %d drug_finding_links", len(drug_finding_links))
        except Exception as exc:
            logger.warning("IRD LLM Call 3 (drug->finding) failed: %s", exc)

    return {
        "evidence_by_icd":    evidence_by_icd    if isinstance(evidence_by_icd,    list) else [],
        "bill_report_links":  bill_report_links   if isinstance(bill_report_links,  list) else [],
        "drug_finding_links": drug_finding_links  if isinstance(drug_finding_links, list) else [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bill categorisation — CPT range-based, disease-agnostic
# ─────────────────────────────────────────────────────────────────────────────

def _categorise_bill_item(description: str, cpt_code: str) -> str:
    """
    Assign a billing category using AMA CPT numeric ranges (authoritative,
    specialty-agnostic). Falls back to HCPCS Level II letter prefix, then
    broad generic description keywords.
    Contains NO disease-specific or drug-name hardcoding.
    """
    cpt_digits = re.sub(r"\D", "", cpt_code or "")
    if cpt_digits:
        try:
            n = int(cpt_digits)
            if   10000 <= n <= 19999: return "Surgical - Integumentary"
            elif 20000 <= n <= 29999: return "Surgical - Musculoskeletal"
            elif 30000 <= n <= 39999: return "Surgical - Respiratory"
            elif 40000 <= n <= 49999: return "Surgical - Digestive"
            elif 50000 <= n <= 59999: return "Surgical - Urinary & Reproductive"
            elif 60000 <= n <= 69999: return "Surgical - Endocrine & Nervous"
            elif 70000 <= n <= 79999: return "Radiology & Imaging"
            elif 80000 <= n <= 89999: return "Laboratory & Pathology"
            elif 90000 <= n <= 99999: return "Evaluation, Medicine & Procedures"
        except ValueError:
            pass

    prefix = (cpt_code or "").strip().upper()[:1]
    hcpcs_map = {
        "A": "Medical Supplies & Transport",
        "B": "Enteral & Parenteral Therapy",
        "C": "Outpatient Hospital",
        "D": "Dental",
        "E": "Durable Medical Equipment",
        "G": "Procedures & Professional Services",
        "H": "Behavioural Health",
        "J": "Drugs Administered by Injection",
        "K": "Durable Medical Equipment (temp)",
        "L": "Orthotics & Prosthetics",
        "M": "Medical Services",
        "P": "Pathology & Lab",
        "Q": "Miscellaneous Services",
        "R": "Diagnostic Radiology",
        "S": "Private Payer / Temporary Codes",
        "T": "State Medicaid",
        "V": "Vision & Hearing",
    }
    if prefix in hcpcs_map:
        return hcpcs_map[prefix]

    desc_lower  = (description or "").lower()
    drug_forms  = ["tablet", "capsule", "injection", "syrup", "solution", "cream",
                   "patch", "inhaler", "suppository", "drops", "gel", "vial",
                   "ampoule", "sachet", "powder", "lotion"]
    admin_terms = ["consultation", "counseling", "counselling", "dispensing",
                   "handling", "filing", "reminder", "setup", "activation",
                   "document", "review service", "outpatient visit"]

    if any(k in desc_lower for k in drug_forms):
        return "Medications & Dispensing"
    if any(k in desc_lower for k in admin_terms):
        return "Administrative & Consultation"
    return "Other Services"


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — PDF generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_pdf(
    patient: Patient,
    discharge: DischargeHistory,
    icd_codes: List[Dict[str, str]],
    icd_failed: bool,
    reports: List[Report],
    bills: List[Bill],
    alignment: Dict[str, List],
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # ── Colour palette ────────────────────────────────────────────────────────
    NAVY        = colors.HexColor("#1a3a5c")
    TEAL        = colors.HexColor("#0e7490")
    TEAL_LIGHT  = colors.HexColor("#e0f2f7")
    LIGHT_GRAY  = colors.HexColor("#f1f5f9")
    MID_GRAY    = colors.HexColor("#64748b")
    DARK_GRAY   = colors.HexColor("#334155")
    ROW_ALT     = colors.HexColor("#f8fafc")
    FLAG_RED_BG = colors.HexColor("#fee2e2")
    FLAG_AMB_BG = colors.HexColor("#fef9c3")
    FLAG_RED_TX = colors.HexColor("#991b1b")
    FLAG_AMB_TX = colors.HexColor("#92400e")
    LINK_BLUE   = colors.HexColor("#1d4ed8")
    WHITE       = colors.white

    # ── Page setup ────────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=2 * cm,    bottomMargin=2 * cm,
    )
    PAGE_W = A4[0] - 3.6 * cm   # usable width ~17.4 cm

    # ── Styles ────────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()["Normal"]

    def S(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base, **kw)

    title_s    = S("IRDTitle",  fontSize=15, alignment=TA_CENTER, spaceAfter=3,
                               textColor=NAVY, fontName="Helvetica-Bold")
    sub_s      = S("IRDSub",    fontSize=7.5, alignment=TA_CENTER,
                               textColor=MID_GRAY, spaceAfter=2)
    sec_hdr_s  = S("IRDSecHdr", fontSize=9, textColor=WHITE,
                               fontName="Helvetica-Bold", leading=13, leftIndent=5)
    label_s    = S("IRDLabel",  fontSize=8, leading=11,
                               fontName="Helvetica-Bold", textColor=NAVY)
    cell_s     = S("IRDCell",   fontSize=8, leading=11)
    cell_b     = S("IRDCellB",  fontSize=8, leading=11, fontName="Helvetica-Bold")
    cell_teal  = S("IRDCellT",  fontSize=8, leading=11,
                               fontName="Helvetica-Bold", textColor=TEAL)
    cell_r     = S("IRDCellR",  fontSize=8, leading=11, alignment=TA_RIGHT)
    cell_rb    = S("IRDCellRB", fontSize=8, leading=11, alignment=TA_RIGHT,
                               fontName="Helvetica-Bold")
    italic_s   = S("IRDItalic", fontSize=7.5, leading=11,
                               fontName="Helvetica-Oblique", textColor=MID_GRAY)
    link_s     = S("IRDLink",   fontSize=9,  textColor=LINK_BLUE)
    small_s    = S("IRDSmall",  fontSize=7,  textColor=MID_GRAY, alignment=TA_CENTER)
    warn_s     = S("IRDWarn",   fontSize=9,  textColor=FLAG_RED_TX)
    # Evidence trail specific
    icd_hdr_s  = S("IRDIcdHdr", fontSize=8.5, fontName="Helvetica-Bold",
                               textColor=TEAL, leading=12)
    evidence_s = S("IRDEvid",   fontSize=8, leading=11, leftIndent=10,
                               textColor=DARK_GRAY)
    why_s      = S("IRDWhy",    fontSize=7.5, leading=11, leftIndent=20,
                               fontName="Helvetica-Oblique", textColor=MID_GRAY)
    billed_s   = S("IRDBilled", fontSize=7.5, leading=11, leftIndent=20,
                               textColor=TEAL)
    flag_hi_s  = S("IRDFlagHi", fontSize=7.5, fontName="Helvetica-Bold",
                               textColor=FLAG_RED_TX)
    flag_lo_s  = S("IRDFlagLo", fontSize=7.5, fontName="Helvetica-Bold",
                               textColor=FLAG_AMB_TX)

    now     = datetime.now(TIMEZONE)
    now_str = now.strftime("%d %b %Y, %I:%M %p IST")

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _section_bar(title: str) -> Table:
        t = Table([[Paragraph(title, sec_hdr_s)]], colWidths=[PAGE_W])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ]))
        return t

    def _tbl_ts(hdr_color=NAVY) -> list:
        return [
            ("BACKGROUND",    (0, 0), (-1, 0), hdr_color),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ]

    def _alt(ts: list, n: int, start: int = 2) -> list:
        for i in range(start, n, 2):
            ts.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GRAY))
        return ts

    def _flag_s(flag: str) -> ParagraphStyle:
        f = (flag or "").upper()
        if any(w in f for w in ("CRITICAL", "HIGH", "POSITIVE", "ABNORMAL")):
            return flag_hi_s
        if "LOW" in f:
            return flag_lo_s
        return cell_s

    story: list = []
    # Pre-compute all flagged lab findings — used as guaranteed fallback across
    # all sections when LLM alignment returns empty or mismatched data
    all_abnormal: List[Dict] = _build_abnormal_findings(reports)

    # ═════════════════════════════════════════════════════════════════════════
    # 1. HEADER
    # ═════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("INSURANCE READY DOCUMENT (IRD)", title_s))
    story.append(Paragraph(
        "Prepared for Insurance Claim Submission  |  Confidential Medical Record",
        sub_s,
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=6))

    # ═════════════════════════════════════════════════════════════════════════
    # 2. PATIENT INFORMATION
    # ═════════════════════════════════════════════════════════════════════════
    story.append(_section_bar("PATIENT INFORMATION"))
    story.append(Spacer(1, 0.2 * cm))

    dob_str  = patient.dob.strftime("%d %b %Y") if patient.dob else "N/A"
    disc_str = (
        discharge.discharge_date.strftime("%d %b %Y")
        if discharge.discharge_date else "N/A"
    )
    adm_str  = (
        discharge.admission_date.strftime("%d %b %Y")
        if getattr(discharge, "admission_date", None)
        else "N/A"
    )

    info_rows = [
        [Paragraph("Patient Name",   label_s), Paragraph(_safe_text(patient.full_name or "N/A"), cell_s),
         Paragraph("Date of Birth",  label_s), Paragraph(dob_str, cell_s)],
        [Paragraph("Gender",         label_s), Paragraph(_safe_text(patient.gender or "N/A"), cell_s),
         Paragraph("Admission Date", label_s), Paragraph(adm_str, cell_s)],
        [Paragraph("Discharge Date", label_s), Paragraph(disc_str, cell_s),
         Paragraph("Document Date",  label_s), Paragraph(now_str, cell_s)],
    ]
    info_tbl = Table(info_rows, colWidths=[2.7 * cm, 5.5 * cm, 2.7 * cm, 6.5 * cm])
    info_ts = [
        ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
    ]
    for i in range(1, len(info_rows), 2):
        info_ts.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GRAY))
    info_tbl.setStyle(TableStyle(info_ts))
    story.append(info_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # ═════════════════════════════════════════════════════════════════════════
    # 3. ICD-10 DIAGNOSIS CODES
    # ═════════════════════════════════════════════════════════════════════════
    story.append(_section_bar("ICD-10 DIAGNOSIS CODES"))
    story.append(Spacer(1, 0.15 * cm))

    if icd_failed:
        story.append(Paragraph(
            "WARNING: ICD-10 code generation failed. Please assign codes manually.",
            warn_s,
        ))
    elif not icd_codes:
        story.append(Paragraph("No ICD-10 codes were generated.", cell_s))
    else:
        icd_rows = [[
            Paragraph("Code",               cell_b),
            Paragraph("Diagnosis Title",    cell_b),
            Paragraph("Clinical Rationale", cell_b),
        ]]
        for item in icd_codes:
            icd_rows.append([
                Paragraph(_safe_text(item.get("code") or ""),      cell_teal),
                Paragraph(_safe_text(item.get("title") or ""),     cell_s),
                Paragraph(_safe_text(item.get("rationale") or ""), cell_s),
            ])
        icd_tbl = Table(
            icd_rows,
            colWidths=[2 * cm, 5.5 * cm, PAGE_W - 7.5 * cm],
            repeatRows=1,
        )
        _ts3 = _tbl_ts()
        _ts3 = _alt(_ts3, len(icd_rows))
        icd_tbl.setStyle(TableStyle(_ts3))
        story.append(icd_tbl)

    story.append(Spacer(1, 0.3 * cm))

    # ═════════════════════════════════════════════════════════════════════════
    # 4. CLINICAL EVIDENCE TRAIL
    #
    # Layout per ICD code (kept together on page):
    #   [TEAL background] CODE — Diagnosis Title
    #   Clinical basis: <one-sentence summary>
    #   For each supporting finding:
    #     + Test Name: Result units [FLAG]  (Report name)
    #       Why: reason this result supports the diagnosis
    #       Billed: CPT description  $amount
    # ═════════════════════════════════════════════════════════════════════════
    story.append(_section_bar("CLINICAL EVIDENCE TRAIL"))
    story.append(Spacer(1, 0.15 * cm))

    evidence_by_icd    = alignment.get("evidence_by_icd") or []
    bill_report_links  = alignment.get("bill_report_links") or []
    drug_finding_links = alignment.get("drug_finding_links") or []

    # Build fast lookup: normalised CPT/description -> linked_finding string
    # Populated from both procedure links (Call 2) and drug links (Call 3)
    _lf_by_cpt:  Dict[str, str] = {}
    _lf_by_desc: Dict[str, str] = {}

    for lf in bill_report_links:
        ck = (lf.get("cpt_code") or "").strip()
        dk = (lf.get("description") or "").lower().strip()
        lv = (lf.get("linked_finding") or "").strip()
        if ck: _lf_by_cpt[ck]  = lv
        if dk: _lf_by_desc[dk] = lv

    # Drug links (Call 3) -- keyed by description since drug line items rarely have CPT codes
    # Also kept as a list for substring-match fallback (LLM often paraphrases drug names)
    _drug_lf_entries: List[Tuple[str, str]] = []
    for dl in drug_finding_links:
        dk = (dl.get("description") or "").lower().strip()
        lv = (dl.get("linked_finding") or "").strip()
        lr = (dl.get("linked_report") or "").strip()
        ic = (dl.get("icd_code") or "").strip()
        # Compose a rich label: "TestName: Value (Report) [ICD]"
        if lv and dk:
            full_lv = lv
            if lr:
                full_lv += f" ({lr})"
            if ic:
                full_lv += f" [{ic}]"
            _lf_by_desc[dk] = full_lv
            _drug_lf_entries.append((dk, full_lv))

    # Build lookup: test_name (lower) -> list of bill items ordered for it
    _bills_for_test: Dict[str, List[Dict]] = defaultdict(list)
    for bill in bills:
        for d in (bill.descriptions or []):
            ck = (d.cpt_code or "").strip()
            dk = (d.description or "").lower().strip()
            lv = (_lf_by_cpt.get(ck) or _lf_by_desc.get(dk) or "").lower().strip()
            if lv:
                _bills_for_test[lv].append({
                    "cpt":   _safe_text(d.cpt_code or "-"),
                    "desc":  _safe_text(d.description or ""),
                    "total": float(d.total_price or 0),
                })

    if not icd_codes:
        # ICD coding completely failed — show raw abnormal findings from reports
        if all_abnormal:
            story.append(Paragraph(
                "<i>ICD-10 coding could not be completed. "
                "Abnormal test findings listed below as supporting clinical evidence:</i>",
                italic_s,
            ))
            story.append(Spacer(1, 0.1 * cm))
            _fb_by_report: Dict[str, List[Dict]] = defaultdict(list)
            for _fb in all_abnormal:
                _fb_by_report[_fb["report"]].append(_fb)
            for _rpt_name, _fbs in _fb_by_report.items():
                _rpt_bar = Table(
                    [[Paragraph(f"<b>{_safe_text(_rpt_name)}</b>", icd_hdr_s)]],
                    colWidths=[PAGE_W],
                )
                _rpt_bar.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, -1), TEAL_LIGHT),
                    ("TOPPADDING",    (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                    ("LINEBELOW",     (0, 0), (-1, -1), 0.6, TEAL),
                ]))
                story.append(_rpt_bar)
                for _fb in _fbs:
                    _tn = _safe_text(_fb["test_name"])
                    _rs = f"{_safe_text(_fb['result'])} {_safe_text(_fb['units'])}".strip()
                    _fl = _safe_text(_fb["flag"])
                    if _fl and any(w in _fl.upper() for w in ("CRITICAL", "HIGH", "POSITIVE", "ABNORMAL")):
                        _fm = f"  <font color='#991b1b' size='7'><b>[{_fl}]</b></font>"
                    elif _fl and "LOW" in _fl.upper():
                        _fm = f"  <font color='#92400e' size='7'><b>[{_fl}]</b></font>"
                    else:
                        _fm = f"  [{_fl}]" if _fl else ""
                    story.append(Paragraph(
                        f"<b>+</b>  <b>{_tn}:</b>  {_rs}{_fm}", evidence_s
                    ))
                story.append(Spacer(1, 0.12 * cm))
        else:
            story.append(Paragraph("No clinical evidence data available.", italic_s))
    else:
        # Build evidence map keyed by ICD code for O(1) lookup
        ev_map: Dict[str, Dict] = {
            e.get("icd_code", ""): e for e in evidence_by_icd
        }

        # Iterate over RAG-returned ICD codes (source of truth for which codes exist)
        for icd in icd_codes:
            code    = _safe_text(icd.get("code") or "")
            title   = _safe_text(icd.get("title") or "")
            ev      = ev_map.get(code) or ev_map.get(code.split(".")[0]) or {}
            findings = ev.get("findings") or []
            summary  = _safe_text(
                ev.get("clinical_summary") or icd.get("rationale") or ""
            )

            block: list = []

            # ── ICD header bar ──
            icd_bar = Table(
                [[
                    Paragraph(f"<b>{code}</b>", cell_teal),
                    Paragraph(f"<b>{title}</b>", icd_hdr_s),
                ]],
                colWidths=[2.1 * cm, PAGE_W - 2.1 * cm],
            )
            icd_bar.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), TEAL_LIGHT),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW",     (0, 0), (-1, -1), 0.8, TEAL),
            ]))
            block.append(icd_bar)

            # ── Clinical basis ──
            if summary:
                block.append(Spacer(1, 0.05 * cm))
                block.append(Paragraph(
                    f"<i>Clinical basis:</i>  {summary}", italic_s,
                ))

            # ── Supporting findings ──
            if findings:
                block.append(Spacer(1, 0.05 * cm))
                for f in findings:
                    tname   = _safe_text(f.get("test_name") or "")
                    result  = _safe_text(f.get("result") or "")
                    units   = _safe_text(f.get("units") or "")
                    flag    = _safe_text(f.get("flag") or "")
                    reason  = _safe_text(f.get("reason") or "")
                    result_str = f"{result} {units}".strip()

                    # Determine flag colour tag
                    if flag and any(w in flag.upper() for w in
                                    ("CRITICAL", "HIGH", "POSITIVE", "ABNORMAL")):
                        flag_markup = (
                            f"  <font color='#991b1b' size='7'><b>[{flag}]</b></font>"
                        )
                    elif flag and "LOW" in flag.upper():
                        flag_markup = (
                            f"  <font color='#92400e' size='7'><b>[{flag}]</b></font>"
                        )
                    else:
                        flag_markup = f"  [{flag}]" if flag else ""

                    # Finding line
                    block.append(Paragraph(
                        f"<b>+</b>  <b>{tname}:</b>  {result_str}{flag_markup}",
                        evidence_s,
                    ))

                    # Why this finding supports the diagnosis
                    if reason:
                        block.append(Paragraph(
                            f"<i>Why:</i>  {reason}", why_s,
                        ))

                    # Bill items that were ordered for this test
                    test_key = tname.lower().strip()
                    result_key = result_str.lower().strip()
                    matched = (
                        _bills_for_test.get(test_key)
                        or _bills_for_test.get(result_key)
                        or []
                    )
                    for bi in matched[:3]:
                        block.append(Paragraph(
                            f"<b>Billed:</b>  {bi['desc']}"
                            f"  (CPT {bi['cpt']})"
                            f"  &nbsp; <b>${bi['total']:,.2f}</b>",
                            billed_s,
                        ))
            else:
                # LLM Call 1 returned no findings for this code — fall back to ALL
                # abnormal lab results from the actual clinical reports
                if all_abnormal:
                    block.append(Paragraph(
                        "<i>Supporting abnormal findings from clinical reports:</i>",
                        italic_s,
                    ))
                    block.append(Spacer(1, 0.05 * cm))
                    for _af in all_abnormal[:8]:
                        _tn = _safe_text(_af["test_name"])
                        _rs = f"{_safe_text(_af['result'])} {_safe_text(_af['units'])}".strip()
                        _fl = _safe_text(_af["flag"])
                        _rp = _safe_text(_af["report"])
                        if _fl and any(w in _fl.upper() for w in
                                       ("CRITICAL", "HIGH", "POSITIVE", "ABNORMAL")):
                            _fm = f"  <font color='#991b1b' size='7'><b>[{_fl}]</b></font>"
                        elif _fl and "LOW" in _fl.upper():
                            _fm = f"  <font color='#92400e' size='7'><b>[{_fl}]</b></font>"
                        else:
                            _fm = f"  [{_fl}]" if _fl else ""
                        _rm = (
                            f"  <font color='#64748b' size='7'>({_rp})</font>"
                            if _rp else ""
                        )
                        block.append(Paragraph(
                            f"<b>+</b>  <b>{_tn}:</b>  {_rs}{_fm}{_rm}",
                            evidence_s,
                        ))
                else:
                    block.append(Paragraph(
                        "No abnormal test findings available for this record.", italic_s,
                    ))

            block.append(Spacer(1, 0.15 * cm))
            story.append(KeepTogether(block))

    story.append(Spacer(1, 0.3 * cm))

    # ═════════════════════════════════════════════════════════════════════════
    # 5. BILLING SUMMARY — category-grouped CPT table
    # ═════════════════════════════════════════════════════════════════════════
    story.append(_section_bar("BILLING SUMMARY"))
    story.append(Spacer(1, 0.15 * cm))

    all_desc_rows = [
        (b, d) for b in bills for d in (b.descriptions or [])
    ]

    if not all_desc_rows:
        story.append(Paragraph("No billing line items found.", italic_s))
    else:
        cat_groups: Dict[str, list] = defaultdict(list)
        for b, d in all_desc_rows:
            cat = _categorise_bill_item(d.description or "", d.cpt_code or "")
            cat_groups[cat].append((b, d))

        def _cat_key(c: str) -> str:
            if c.startswith("Other"):          return "zz" + c
            if c.startswith("Administrative"): return "zy" + c
            if c.startswith("Medications"):    return "zx" + c
            return c

        ordered_cats = sorted(cat_groups.keys(), key=_cat_key)

        COL_W = [1.7 * cm, 6.3 * cm, 0.8 * cm, 1.7 * cm, 1.7 * cm, 4 * cm]

        b_data: list = []
        b_ts:   list = []
        grand   = 0.0
        ri      = 0

        # Header
        b_data.append([
            Paragraph("CPT",            cell_b),
            Paragraph("Description",    cell_b),
            Paragraph("Qty",            cell_b),
            Paragraph("Unit",           cell_b),
            Paragraph("Total",          cell_b),
            Paragraph("Test / Clinical Reason", cell_b),
        ])
        b_ts += [
            ("BACKGROUND",    (0, ri), (-1, ri), NAVY),
            ("TEXTCOLOR",     (0, ri), (-1, ri), WHITE),
            ("FONTNAME",      (0, ri), (-1, ri), "Helvetica-Bold"),
            ("TOPPADDING",    (0, ri), (-1, ri), 4),
            ("BOTTOMPADDING", (0, ri), (-1, ri), 4),
        ]
        ri += 1

        for cat in ordered_cats:
            items = cat_groups[cat]

            # Category sub-header
            _cat_style = S(f"BC{ri}", fontSize=7.5, fontName="Helvetica-Bold",
                           textColor=WHITE, leading=11)
            b_data.append([Paragraph(_safe_text(cat), _cat_style), "", "", "", "", ""])
            b_ts += [
                ("BACKGROUND",    (0, ri), (-1, ri), TEAL),
                ("SPAN",          (0, ri), (-1, ri)),
                ("TOPPADDING",    (0, ri), (-1, ri), 3),
                ("BOTTOMPADDING", (0, ri), (-1, ri), 3),
                ("LEFTPADDING",   (0, ri), (-1, ri), 6),
            ]
            ri += 1

            cat_sub = 0.0
            for idx, (b, d) in enumerate(items):
                lf = (
                    _lf_by_cpt.get((d.cpt_code or "").strip())
                    or _lf_by_desc.get((d.description or "").lower().strip())
                    or ""
                )

                # For medication rows: exact key often misses because LLM paraphrases drug names.
                # Fallback 1 — substring / shared-word match against drug_finding_links entries.
                if not lf and cat == "Medications & Dispensing" and _drug_lf_entries:
                    dk_lower = (d.description or "").lower().strip()
                    for entry_key, entry_val in _drug_lf_entries:
                        if not entry_key:
                            continue
                        # Accept if one string contains the other, or if they share a meaningful word
                        if entry_key in dk_lower or dk_lower in entry_key:
                            lf = entry_val
                            break
                        shared = [
                            w for w in entry_key.split()
                            if len(w) > 4 and w in dk_lower
                        ]
                        if shared:
                            lf = entry_val
                            break

                # Fallback 2 — normalize drug name (strip dose/strength/form suffix)
                # and re-attempt match (handles LLM paraphrasing of brand/generic names)
                if not lf and cat == "Medications & Dispensing" and _drug_lf_entries:
                    def _norm_drug(s: str) -> str:
                        s = re.sub(r'\d+\.?\d*\s*(mg|mcg|ml|g|iu|units?)\b', ' ', s,
                                   flags=re.IGNORECASE)
                        s = re.sub(
                            r'\b(tab(let)?s?|cap(sule)?s?|inj(ection)?|syr(up)?|'
                            r'susp(ension)?|sol(ution)?|cream|drops?|gel|vial|ampoule|'
                            r'sachet|powder|lotion|hcl|sodium|phosphate|chloride|'
                            r'sulphate|sulfate|acetate)\b',
                            ' ', s, flags=re.IGNORECASE,
                        )
                        s = re.sub(r'\([^)]*\)', ' ', s)
                        return re.sub(r'\s+', ' ', s).strip().lower()
                    nd = _norm_drug(d.description or "")
                    nw = [w for w in nd.split() if len(w) > 3]
                    for _ek, _ev in _drug_lf_entries:
                        ne = _norm_drug(_ek)
                        ew = [w for w in ne.split() if len(w) > 3]
                        if nd and ne and (
                            nd == ne
                            or nd in ne or ne in nd
                            or any(w in ew for w in nw)
                        ):
                            lf = _ev
                            break

                # Fallback 3 — token-overlap against actual flagged lab findings from reports
                if not lf and cat == "Medications & Dispensing" and all_abnormal:
                    _desc_tok = set(
                        w for w in re.split(r"[\s\-/(),]+", (d.description or "").lower())
                        if len(w) > 3
                    )
                    _best_af, _best_sc = None, 0
                    for _af in all_abnormal:
                        _af_tok = set(
                            w for w in re.split(
                                r"[\s\-/(),]+",
                                (_af["test_name"] + " " + _af.get("section", "")).lower(),
                            )
                            if len(w) > 3
                        )
                        _sc = len(_desc_tok & _af_tok)
                        if _sc > _best_sc:
                            _best_sc, _best_af = _sc, _af
                    if _best_af:
                        lf = f"{_best_af['test_name']}: {_best_af['result']}"
                        if _best_af["units"]:
                            lf += f" {_best_af['units']}"
                        lf += f" [{_best_af['flag']}] ({_best_af['report']})"

                # Fallback 4 — guaranteed non-empty: first abnormal finding or ICD rationale
                if not lf and cat == "Medications & Dispensing":
                    if all_abnormal:
                        _gaf = all_abnormal[0]
                        lf = f"{_gaf['test_name']}: {_gaf['result']}"
                        if _gaf["units"]:
                            lf += f" {_gaf['units']}"
                        lf += f" [{_gaf['flag']}]"
                    elif icd_codes:
                        lf = _safe_text(icd_codes[0].get("rationale") or "")

                unit  = float(d.unit_price  or 0)
                total = float(d.total_price or 0)
                cat_sub += total
                grand   += total

                row_bg = WHITE if idx % 2 == 0 else ROW_ALT
                b_data.append([
                    Paragraph(_safe_text(d.cpt_code or "-"),           cell_s),
                    Paragraph(_safe_text(_trunc(d.description or "")), cell_s),
                    Paragraph(str(d.qty or 1),                         cell_s),
                    Paragraph(f"${unit:,.2f}",                         cell_r),
                    Paragraph(f"${total:,.2f}",                        cell_r),
                    Paragraph(_safe_text(lf), cell_s) if lf
                    else Paragraph("-", italic_s),
                ])
                b_ts += [
                    ("BACKGROUND",    (0, ri), (-1, ri), row_bg),
                    ("TOPPADDING",    (0, ri), (-1, ri), 2),
                    ("BOTTOMPADDING", (0, ri), (-1, ri), 2),
                    ("FONTSIZE",      (0, ri), (-1, ri), 7.5),
                ]
                ri += 1

            # Subtotal
            b_data.append([
                "", "", "", "",
                Paragraph(f"<b>${cat_sub:,.2f}</b>", cell_rb),
                Paragraph(f"<i>{_safe_text(cat)}</i>", italic_s),
            ])
            b_ts += [
                ("BACKGROUND",    (0, ri), (-1, ri), LIGHT_GRAY),
                ("TOPPADDING",    (0, ri), (-1, ri), 2),
                ("BOTTOMPADDING", (0, ri), (-1, ri), 2),
                ("LINEABOVE",     (0, ri), (-1, ri), 0.4, MID_GRAY),
            ]
            ri += 1

        # Grand total
        _gt_s = S("GT", fontSize=8, fontName="Helvetica-Bold",
                  textColor=WHITE, alignment=TA_RIGHT)
        b_data.append(["", "", "",
                        Paragraph("GRAND TOTAL", _gt_s),
                        Paragraph(f"${grand:,.2f}", _gt_s),
                        ""])
        b_ts += [
            ("BACKGROUND",    (0, ri), (-1, ri), NAVY),
            ("TOPPADDING",    (0, ri), (-1, ri), 5),
            ("BOTTOMPADDING", (0, ri), (-1, ri), 5),
        ]

        bill_tbl = Table(b_data, colWidths=COL_W, repeatRows=1)
        bill_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN",   (0, 0), (-1, -1), "TOP"),
            ("GRID",     (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ] + b_ts))
        story.append(bill_tbl)

    story.append(Spacer(1, 0.3 * cm))

    # ═════════════════════════════════════════════════════════════════════════
    # 6. MEDICAL REPORTS & DOCUMENTS
    # ═════════════════════════════════════════════════════════════════════════
    story.append(_section_bar("MEDICAL REPORTS &amp; DOCUMENTS"))
    story.append(Spacer(1, 0.15 * cm))

    reports_with_urls = [r for r in reports if r.report_url]
    if not reports_with_urls:
        story.append(Paragraph("No report documents available.", cell_s))
    else:
        for rpt in reports_with_urls:
            date_part = rpt.report_date.strftime("%d %b %Y") if rpt.report_date else ""
            label = _safe_text(rpt.report_name or "Report")
            if date_part:
                label += f"  ({date_part})"
            story.append(Paragraph(
                f'<a href="{rpt.report_url}" color="#1d4ed8"><u>{label}</u></a>',
                link_s,
            ))
            if rpt.specimen_type:
                story.append(Paragraph(
                    f"Specimen: {_safe_text(rpt.specimen_type)}", italic_s,
                ))
            story.append(Spacer(1, 0.1 * cm))

    story.append(Spacer(1, 0.25 * cm))

    # ═════════════════════════════════════════════════════════════════════════
    # 7. BILLS & INVOICES
    # ═════════════════════════════════════════════════════════════════════════
    story.append(_section_bar("BILLS &amp; INVOICES"))
    story.append(Spacer(1, 0.15 * cm))

    bills_with_urls = [b for b in bills if b.bill_url]
    if not bills_with_urls:
        story.append(Paragraph("No bill documents available.", cell_s))
    else:
        for bill in bills_with_urls:
            date_str = bill.invoice_date.strftime("%d %b %Y") if bill.invoice_date else "N/A"
            label    = f"Invoice #{_safe_text(bill.invoice_number or '')}  -  {date_str}"
            if bill.total_amount:
                label += f"   |   Total: ${float(bill.total_amount):,.2f}"
            story.append(Paragraph(
                f'<a href="{bill.bill_url}" color="#1d4ed8"><u>{label}</u></a>',
                link_s,
            ))
            story.append(Spacer(1, 0.1 * cm))

    story.append(Spacer(1, 0.5 * cm))

    # ═════════════════════════════════════════════════════════════════════════
    # FOOTER
    # ═════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceAfter=4))
    story.append(Paragraph(
        "This document is auto-generated for insurance claim submission purposes only and does not "
        "replace a physician's clinical judgement or official medical records.  "
        f"|  Generated: {now_str}",
        small_s,
    ))

    doc.build(story)
    return buffer.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 — Upload to Cloudinary
# ─────────────────────────────────────────────────────────────────────────────

def _upload_to_cloudinary(pdf_bytes: bytes, discharge_id: int, patient_id: int) -> str:
    from services.storage.cloudinary_storage import CloudinaryStorage
    try:
        result = CloudinaryStorage.upload_pdf(
            file=io.BytesIO(pdf_bytes),
            filename=f"IRD_{discharge_id}_{int(time.time())}.pdf",
            document_type="ird",
            patient_id=patient_id,
        )
        return result["secure_url"]
    except Exception as exc:
        logger.error(
            "Cloudinary upload failed for discharge %s: %s",
            discharge_id, exc, exc_info=True,
        )
        raise RuntimeError(
            f"PDF generation succeeded but Cloudinary upload failed: {exc}"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Shared DB fetch helper — DRY, used by both orchestrators
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_all_data(
    discharge_id: int, db: Session
) -> Tuple[DischargeHistory, Patient, List[Report], List[Bill], List[Dict]]:
    """
    Fetch all DB data needed for IRD generation.
    Returns (discharge, patient, reports, bills, medications_payload).
    Raises ValueError if discharge or reports are missing.
    """
    discharge: Optional[DischargeHistory] = (
        db.query(DischargeHistory)
        .filter(DischargeHistory.id == discharge_id)
        .first()
    )
    if not discharge:
        raise ValueError("Discharge record not found")

    patient: Patient = discharge.patient

    reports: List[Report] = (
        db.query(Report)
        .options(joinedload(Report.descriptions))
        .filter(Report.discharge_id == discharge_id)
        .all()
    )
    if not reports:
        raise ValueError(
            f"No clinical reports found for discharge ID: {discharge_id}. "
            "Cannot generate ICD-10 codes."
        )

    bills: List[Bill] = (
        db.query(Bill)
        .options(joinedload(Bill.descriptions))
        .filter(Bill.discharge_id == discharge_id)
        .all()
    )

    # Guard against NULL is_active — some records store NULL instead of False
    meds_orm: List[Medication] = (
        db.query(Medication)
        .options(joinedload(Medication.schedule))
        .filter(
            Medication.discharge_id == discharge_id,
            or_(Medication.is_active == True, Medication.is_active == None),
        )
        .all()
    )
    medications_payload = _build_medications_payload(meds_orm)

    return discharge, patient, reports, bills, medications_payload


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrators
# ─────────────────────────────────────────────────────────────────────────────

def generate_ird(discharge_id: int, db: Session) -> Dict[str, Any]:
    """
    Full IRD generation pipeline for a given discharge_id.

    Raises:
        ValueError:   if discharge not found or no reports exist
        RuntimeError: if Cloudinary upload fails after PDF is generated
    """
    discharge, patient, reports, bills, medications_payload = _fetch_all_data(
        discharge_id, db
    )

    clinical_note         = _format_reports_to_clinical_text(reports)
    icd_codes, icd_failed = _call_icd_lookup(clinical_note)
    alignment             = _call_llm_alignment(icd_codes, reports, bills)

    pdf_bytes = _generate_pdf(
        patient=patient,
        discharge=discharge,
        icd_codes=icd_codes,
        icd_failed=icd_failed,
        reports=reports,
        bills=bills,
        alignment=alignment,
    )

    ird_url = _upload_to_cloudinary(pdf_bytes, discharge_id, patient.id)

    discharge.insurance_ready_url = ird_url
    db.commit()

    return {
        "success":               True,
        "ird_url":               ird_url,
        "icd_codes":             icd_codes,
        "icd_generation_failed": icd_failed,
        "report_count":          len([r for r in reports if r.report_url]),
        "bill_count":            len([b for b in bills if b.bill_url]),
        "patient_name":          patient.full_name,
        "discharge_date":        str(discharge.discharge_date) if discharge.discharge_date else None,
    }


def generate_ird_pdf_bytes(discharge_id: int, db: Session) -> Tuple[bytes, str]:
    """
    Generates only the PDF (no Cloudinary upload) — used by the preview endpoint.
    Returns (pdf_bytes, patient_name).
    """
    discharge, patient, reports, bills, medications_payload = _fetch_all_data(
        discharge_id, db
    )

    clinical_note         = _format_reports_to_clinical_text(reports)
    icd_codes, icd_failed = _call_icd_lookup(clinical_note)
    alignment             = _call_llm_alignment(icd_codes, reports, bills)

    pdf_bytes = _generate_pdf(
        patient=patient,
        discharge=discharge,
        icd_codes=icd_codes,
        icd_failed=icd_failed,
        reports=reports,
        bills=bills,
        alignment=alignment,
    )
    return pdf_bytes, patient.full_name or f"discharge_{discharge_id}"