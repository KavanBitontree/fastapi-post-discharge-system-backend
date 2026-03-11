"""
Bill PDF Parser
---------------
Unified LLM-based extraction with dynamic chunking.

Uses the same extraction flow as reports:
1. Text extraction with pdfplumber
2. Dynamic chunking based on model limits
3. LLM extraction with structured output
4. Result merging
"""

from pathlib import Path
from typing import Optional, BinaryIO
from datetime import date
from decimal import Decimal
from dataclasses import dataclass, field

from services.parsers.unified_pdf_parser import extract_with_chunking, analyze_pdf_for_chunking, extract_with_chunking_from_memory


# ---------------------------------------------------------------------------
# Data classes (mirror the DB schema)
# ---------------------------------------------------------------------------

@dataclass
class BillData:
    """Maps to the `bills` table (patient_id & bill_url set by store script)."""
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    initial_amount: Optional[Decimal] = None   # Gross Charges
    discount_amount: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None


@dataclass
class BillDescriptionItem:
    """Maps to one row in `bill_description`."""
    cpt_code: Optional[str] = None
    description: Optional[str] = None
    qty: Optional[int] = None
    unit_price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None


@dataclass
class ParsedBill:
    """Full parse result returned by :func:`parse_bill_pdf`."""
    bill: BillData = field(default_factory=BillData)
    line_items: list[BillDescriptionItem] = field(default_factory=list)
    patient_name: Optional[str] = None
    patient_email: Optional[str] = None  # Set manually, not extracted from PDF
    patient_dob: Optional[date] = None
    patient_phone: Optional[str] = None
    patient_gender: Optional[str] = None
    discharge_date: Optional[date] = None


# ── Public API ────────────────────────────────────────────────────────────────

def parse_bill_pdf_from_memory(pdf_buffer: BinaryIO, filename: str, strategy: str = "auto") -> 'ParsedBill':
    """
    Extract bill data from PDF in memory (for Vercel deployment).
    
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
    ParsedBill
        Parsed bill with all extracted information
    """
    from services.llm_validators.llm_bill_validator import (
        extract_bill_from_chunk,
        merge_bill_results,
    )
    
    print(f"[parser] Extracting bill from memory: {filename}")
    
    return extract_with_chunking_from_memory(
        pdf_buffer=pdf_buffer,
        filename=filename,
        extraction_function=extract_bill_from_chunk,
        merge_function=merge_bill_results,
        strategy=strategy,
    )


def get_bill_chunking_info(pdf_path: str) -> dict:
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


def parse_bill_pdf(pdf_path: str, strategy: str = "auto") -> 'ParsedBill':
    """
    Extract bill data from PDF file (backward compatibility).
    
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
    ParsedBill
        Parsed bill with all extracted information
    """
    from services.llm_validators.llm_bill_validator import (
        extract_bill_from_chunk,
        merge_bill_results,
    )
    
    from pathlib import Path
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    print(f"[parser] Extracting bill: {path.name}")
    
    return extract_with_chunking(
        pdf_path=str(path),
        extraction_function=extract_bill_from_chunk,
        merge_function=merge_bill_results,
        strategy=strategy,
    )