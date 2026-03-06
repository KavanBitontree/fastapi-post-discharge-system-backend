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
from pathlib import Path
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Optional, BinaryIO
from core.enums import MedicineForm
from services.parsers.unified_pdf_parser import (
    extract_with_chunking,
    analyze_pdf_for_chunking,
    extract_with_chunking_from_memory,
)


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
    patient_id: Optional[int] = None  # Set manually, not extracted from PDF
    patient_email: Optional[str] = None  # Set manually, not extracted from PDF
    patient_phone: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_email: Optional[str] = None
    doctor_speciality: Optional[str] = None
    medications: list[MedicationData] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_prescription_pdf_from_memory(pdf_buffer: BinaryIO, filename: str, strategy: str = "auto") -> 'ParsedPrescription':
    """
    Extract prescription data from PDF in memory (for Vercel deployment).
    
    Parameters
    ----------
    pdf_buffer : BinaryIO
        PDF content in memory
    filename : str
        Original filename for logging
    strategy : str
        "auto" – auto-detect PDF type (default)
        "text" – force text-based extraction
        "vision" – force vision extraction
    
    Returns
    -------
    ParsedPrescription
        Parsed prescription with all extracted information
    """
    from services.llm_validators.llm_prescription_validator import (
        extract_prescription_from_chunk,
        merge_prescription_results,
    )
    
    print(f"[parser] Extracting prescription from memory: {filename}")
    
    return extract_with_chunking_from_memory(
        pdf_buffer=pdf_buffer,
        filename=filename,
        extraction_function=extract_prescription_from_chunk,
        merge_function=merge_prescription_results,
        strategy=strategy,
    )
    """
    Extract prescription data from PDF using LLM with dynamic chunking.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    strategy : str
        "auto" – auto-detect PDF type (default)
        "text" – force text-based extraction
        "vision" – force vision extraction
    
    Returns
    -------
    ParsedPrescription
        Parsed prescription with all extracted information
    """
    from services.llm_validators.llm_prescription_validator import (
        extract_prescription_from_chunk,
        merge_prescription_results,
    )
    
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    print(f"[parser] Extracting prescription: {path.name}")
    
    return extract_with_chunking(
        pdf_path=str(path),
        extraction_function=extract_prescription_from_chunk,
        merge_function=merge_prescription_results,
        strategy=strategy,
    )


def get_prescription_chunking_info(pdf_path: str) -> dict:
    """
    Analyze PDF and return chunking strategy without processing.
    """
    return analyze_pdf_for_chunking(pdf_path)


def extract_raw_text(pdf_path: str) -> str:
    """
    DEPRECATED: For backward compatibility only.
    Use unified_pdf_parser.extract_text_from_pdf instead.
    """
    from services.parsers.unified_pdf_parser import extract_text_from_pdf
    text, _, _ = extract_text_from_pdf(pdf_path)
    return text


def parse_prescription_pdf(pdf_path: str, strategy: str = "auto") -> 'ParsedPrescription':
    """
    Extract prescription data from PDF file (backward compatibility).
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    strategy : str
        "auto" – auto-detect PDF type (default)
        "text" – force text-based extraction
        "vision" – force vision extraction
    
    Returns
    -------
    ParsedPrescription
        Parsed prescription with all extracted information
    """
    from services.llm_validators.llm_prescription_validator import (
        extract_prescription_from_chunk,
        merge_prescription_results,
    )
    
    from pathlib import Path
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    print(f"[parser] Extracting prescription: {path.name}")
    
    return extract_with_chunking(
        pdf_path=str(path),
        extraction_function=extract_prescription_from_chunk,
        merge_function=merge_prescription_results,
        strategy=strategy,
    )