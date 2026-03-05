"""
Bill PDF Parser  —  regex / table extraction layer
--------------------------------------------------
Extracts structured data from a hospital discharge bill PDF using
pdfplumber.  Returns a :class:`ParsedBill` dataclass.

This is Stage 1.  Its output is passed to
``llm_validators.llm_bill_validator`` which fills any gaps using Groq.
"""

import re
import pdfplumber
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from typing import Optional


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
    patient_email: Optional[str] = None
    patient_dob: Optional[date] = None
    patient_phone: Optional[str] = None
    patient_gender: Optional[str] = None
    discharge_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_money(value: str) -> Optional[Decimal]:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    value = re.split(r"\s*\|\s*Time", value)[0].strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _table_to_dict(table: list) -> dict:
    result = {}
    for row in table:
        if row and len(row) >= 2 and row[0]:
            key = str(row[0]).replace("\n", " ").strip().rstrip(":")
            val = str(row[1]).replace("\n", " ").strip() if row[1] else ""
            result[key] = val
    return result


def _first(*values) -> str:
    """Return the first non-empty value from a list of candidates."""
    for v in values:
        if v:
            return v
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_raw_text(pdf_path: str, use_ocr: bool = False) -> str:
    """
    Extract raw text from PDF.
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


def parse_bill_pdf(pdf_path: str) -> ParsedBill:
    """
    Stage-1 regex/table extraction.

    Handles standard Medicare-style discharge bills.
    Fields that cannot be found are left as ``None`` so the
    LLM validator can fill them in.
    """
    result = ParsedBill()

    with pdfplumber.open(pdf_path) as pdf:

        # ── PAGE 1 ──────────────────────────────────────────────────────
        page1 = pdf.pages[0]
        tables = page1.extract_tables()

        # Invoice / account header
        if len(tables) > 0:
            inv = _table_to_dict(tables[0])
            result.bill.invoice_number = _first(
                inv.get("Invoice #"), inv.get("Invoice No"), inv.get("Bill #"),
                inv.get("Receipt #"), inv.get("Ref No"), inv.get("Account #"),
            )
            result.bill.invoice_date = _parse_date(_first(
                inv.get("Invoice Date"), inv.get("Bill Date"), inv.get("Issue Date"),
            ))
            result.bill.due_date = _parse_date(_first(
                inv.get("Due Date"), inv.get("Payment Due"), inv.get("Pay By"),
            ))

        # Patient demographics
        if len(tables) > 1:
            pat = _table_to_dict(tables[1])
            raw_name = _first(
                pat.get("Patient Name"), pat.get("Patient"), pat.get("Client Name"),
                pat.get("Beneficiary"), pat.get("Member"), pat.get("Victim"),
            )
            if "," in raw_name:
                parts = [p.strip() for p in raw_name.split(",", 1)]
                result.patient_name = f"{parts[1]} {parts[0]}"
            else:
                result.patient_name = raw_name or None

            result.patient_email = _first(pat.get("Patient email"), pat.get("Email")) or None
            result.patient_dob = _parse_date(_first(pat.get("Date of Birth"), pat.get("DOB")))
            result.patient_phone = _first(pat.get("Phone"), pat.get("Mobile"), pat.get("Contact")) or None

            age_sex = _first(pat.get("Age / Sex"), pat.get("Gender"), pat.get("Sex"))
            m = re.search(r"\b(Male|Female|Other)\b", age_sex, re.IGNORECASE)
            result.patient_gender = m.group(1).capitalize() if m else None

        # Admission / discharge
        if len(tables) > 2:
            adm = _table_to_dict(tables[2])
            result.discharge_date = _parse_date(_first(
                adm.get("Discharge Date"), adm.get("Discharge"), adm.get("Release Date"),
            ))

        # Line items table
        if len(tables) > 3:
            for row in tables[3][1:]:
                if not row or not row[0]:
                    continue
                result.line_items.append(BillDescriptionItem(
                    cpt_code=str(row[0]).strip() if row[0] else None,
                    description=str(row[1]).strip() if len(row) > 1 and row[1] else None,
                    qty=int(row[2]) if len(row) > 2 and row[2] and str(row[2]).strip().isdigit() else None,
                    unit_price=_parse_money(row[3]) if len(row) > 3 else None,
                    total_price=(
                        _parse_money(row[5]) if len(row) > 5
                        else _parse_money(row[4]) if len(row) > 4
                        else None
                    ),
                ))

        # ── PAGE 2 — totals ─────────────────────────────────────────────
        if len(pdf.pages) > 1:
            p2 = pdf.pages[1].extract_text() or ""

            def _amt(pattern: str) -> Optional[Decimal]:
                m = re.search(pattern, p2, re.IGNORECASE)
                return _parse_money(m.group(1)) if m else None

            result.bill.initial_amount = _amt(
                r"(?:Gross Charges?|Subtotal|Total Charges?|Sub[-\s]?Total)[:\s]+\$?([\d,]+\.\d{2})"
            )
            result.bill.discount_amount = _amt(
                r"(?:Discount|Contractual Adj\.?)[^:]*:[^\$]*\$?([\d,]+\.\d{2})"
            )
            result.bill.tax_amount = _amt(
                r"(?:Tax|GST|VAT)[^:]*:[^\$]*\$?([\d,]+\.\d{2})"
            )
            result.bill.total_amount = _amt(
                r"(?:TOTAL AMOUNT DUE|Total Due|Balance Due|Amount Owed|Total Payable|Total)[:\s]+\$?([\d,]+\.\d{2})"
            )

    return result
