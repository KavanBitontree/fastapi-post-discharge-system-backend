"""
Prescription PDF Parser  —  regex / table extraction layer
----------------------------------------------------------
Extracts structured data from a hospital prescription PDF using
pdfplumber.  Returns a :class:`ParsedPrescription` dataclass.

This is Stage 1.  Its output is passed to
``llm_validators.llm_prescription_validator`` which fills any gaps using Groq.
"""

import re
import pdfplumber
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Optional
from core.enums import MedicineForm


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RecurrenceData:
    type: str  # "daily" | "every_n_days" | "cyclic"
    every_n_days: Optional[int] = None
    start_date_for_every_n_days: Optional[date] = None
    cycle_take_days: Optional[int] = None
    cycle_skip_days: Optional[int] = None


@dataclass
class ScheduleData:
    before_breakfast: bool = False
    after_breakfast: bool = False
    before_lunch: bool = False
    after_lunch: bool = False
    before_dinner: bool = False
    after_dinner: bool = False


@dataclass
class MedicationData:
    drug_name: str
    strength: Optional[str]
    form_of_medicine: Optional[MedicineForm]
    dosage: str
    frequency_of_dose_per_day: int
    dosing_days: Optional[int]
    prescription_date: Optional[date]
    recurrence: RecurrenceData
    schedule: ScheduleData


@dataclass
class ParsedPrescription:
    rx_number: Optional[str] = None
    rx_date: Optional[date] = None
    patient_email: Optional[str] = None
    patient_phone: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_email: Optional[str] = None
    doctor_speciality: Optional[str] = None
    medications: list[MedicationData] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    value = re.split(r"\s*[—–-]\s*\d{2}/\d{2}/\d{4}", value)[0].strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_days(s: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*days?", s or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_form(s: str) -> MedicineForm:
    mapping = {
        "tablet": MedicineForm.TABLET,
        "capsule": MedicineForm.CAPSULE,
        "syrup": MedicineForm.SYRUP,
        "injection": MedicineForm.INJECTION,
        "drops": MedicineForm.DROPS,
        "cream": MedicineForm.CREAM,
        "ointment": MedicineForm.OINTMENT,
        "inhaler": MedicineForm.INHALER,
        "powder": MedicineForm.POWDER,
    }
    return mapping.get((s or "").strip().lower(), MedicineForm.OTHER)


def _parse_recurrence(raw: str, rx_date: Optional[date]) -> RecurrenceData:
    raw = (raw or "").replace("\n", " ").strip()

    if m := re.search(r"every\s+(\d+)\s*days?", raw, re.IGNORECASE):
        return RecurrenceData(
            type="every_n_days",
            every_n_days=int(m.group(1)),
            start_date_for_every_n_days=rx_date,
        )
    if re.search(r"mon.{0,3}fri|weekdays?|5\s*days?\s*/?\s*week", raw, re.IGNORECASE):
        return RecurrenceData(type="cyclic", cycle_take_days=5, cycle_skip_days=2)

    return RecurrenceData(type="daily")


def _parse_schedule(timing: str) -> tuple[ScheduleData, int]:
    t = (timing or "").lower().replace("\n", " ")
    s = ScheduleData(
        before_breakfast="before breakfast" in t or "empty stomach" in t or "fasting" in t,
        after_breakfast="after breakfast" in t or "with breakfast" in t,
        before_lunch="before lunch" in t,
        after_lunch="after lunch" in t or "with lunch" in t,
        before_dinner="before dinner" in t,
        after_dinner=(
            "after dinner" in t or "with dinner" in t
            or "bedtime" in t or "before bed" in t
            or "before sleep" in t or "at night" in t
            or "before bedtime" in t
        ),
    )
    freq = sum([
        s.before_breakfast, s.after_breakfast,
        s.before_lunch, s.after_lunch,
        s.before_dinner, s.after_dinner,
    ])
    return s, max(freq, 1)


def _table_to_dict(table: list) -> dict:
    result = {}
    for row in table:
        if row and len(row) >= 2 and row[0]:
            key = str(row[0]).replace("\n", " ").strip().rstrip(":")
            val = str(row[1]).replace("\n", " ").strip() if row[1] else ""
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_raw_text(pdf_path: str, use_ocr: bool = False) -> str:
    """
    Extract full plain-text content of every page.
    Automatically detects if OCR is needed for image-based PDFs.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    use_ocr : bool
        Force OCR even for text-based PDFs (default: False)
    """
    # Try to use smart OCR extraction if available
    try:
        from services.parsers.ocr_parser import extract_text_smart
        return extract_text_smart(pdf_path, force_ocr=use_ocr)
    except ImportError:
        # Fallback to pdfplumber extraction if OCR dependencies not installed
        print("  ℹ️  OCR not available, using pdfplumber extraction")
        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n\n".join(parts)


def parse_prescription_pdf(pdf_path: str) -> ParsedPrescription:
    """
    Stage-1 regex/table extraction.

    Handles standard prescription layouts.  Fields that cannot
    be found are left as ``None`` for the LLM validator to fill.
    """
    result = ParsedPrescription()

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        full_text = page.extract_text() or ""

        # Patient block
        if len(tables) > 0:
            pat = _table_to_dict(tables[0])
            result.patient_email = pat.get("Email") or None
            result.patient_phone = pat.get("Phone") or pat.get("Contact") or None

        # Prescription meta
        if len(tables) > 1:
            rx = _table_to_dict(tables[1])
            result.rx_number = (
                rx.get("Prescription #") or rx.get("Rx #")
                or rx.get("Rx No") or rx.get("Ref #") or None
            )
            result.rx_date = _parse_date(
                rx.get("Rx Date", "") or rx.get("Date", "") or rx.get("Prescription Date", "")
            )

        # Medications table
        if len(tables) > 2:
            for row in tables[2][1:]:
                if not row or not row[1]:
                    continue

                drug_name = str(row[1]).strip()
                strength = str(row[2]).strip() if len(row) > 2 and row[2] else None
                form = _parse_form(str(row[3]).strip() if len(row) > 3 and row[3] else "")
                dosage = str(row[4]).strip() if len(row) > 4 and row[4] else "1"
                timing_raw = str(row[5]).strip() if len(row) > 5 and row[5] else ""
                duration_raw = str(row[6]).strip() if len(row) > 6 and row[6] else ""
                recurrence_raw = str(row[7]).strip() if len(row) > 7 and row[7] else "Daily"

                schedule, freq = _parse_schedule(timing_raw)
                recurrence = _parse_recurrence(recurrence_raw, result.rx_date)

                result.medications.append(MedicationData(
                    drug_name=drug_name,
                    strength=strength,
                    form_of_medicine=form,
                    dosage=dosage,
                    frequency_of_dose_per_day=freq,
                    dosing_days=_parse_days(duration_raw),
                    prescription_date=result.rx_date,
                    recurrence=recurrence,
                    schedule=schedule,
                ))

        # Doctor info from free text
        doc_match = re.search(
            r"(?:Prescribed By|Prescribing Physician|Doctor|Dr)[:\s]*\n?(Dr\.?\s[\w\s.,]+)\n([\w\s&\-,]+)\n.*?[Ee]mail[:\s]*([\w.\-+@]+)",
            full_text, re.DOTALL,
        )
        if doc_match:
            result.doctor_name = doc_match.group(1).strip()
            result.doctor_speciality = doc_match.group(2).strip()
            result.doctor_email = doc_match.group(3).strip()

    return result
