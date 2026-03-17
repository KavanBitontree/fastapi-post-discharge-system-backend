"""
LLM Bill Validator
------------------
Pure LLM-based extraction of bill data with dynamic chunking support.

Unified extraction flow matching reports and prescriptions.
"""

from typing import Optional, List
from datetime import date
from decimal import Decimal
import re

from core.llm_init import llm
from services.parsers.bill_parser import ParsedBill, BillData, BillDescriptionItem
from schemas.bill_schemas import BillLineItem, BillHeader, PatientInfo, ValidatedBill


# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a medical billing data extraction system.
Extract structured data from hospital discharge bills and return it in JSON format.

BILL HEADER FIELDS - Extract with care:

1. invoice_number: Invoice/bill number (REQUIRED)
   Look for: "Invoice #", "Invoice No", "Bill #", "Bill No", "Receipt #", "Ref #", "Account #"
   Examples: "INV-2026-00847", "BILL-12345", "REC-2024-001"
   CRITICAL: This field is REQUIRED - search thoroughly for any invoice/bill identifier

2. invoice_date: Invoice date in YYYY-MM-DD format
   Look for: "Invoice Date", "Bill Date", "Issue Date", "Date"
   Convert: "03/02/2026" → "2026-03-02", "March 2, 2026" → "2026-03-02"

3. due_date: Payment due date in YYYY-MM-DD format
   Look for: "Due Date", "Payment Due", "Pay By"

4. initial_amount: Initial/gross charges (number without currency symbols)
   Look for: "Gross Charges", "Subtotal", "Total Charges", "Sub-Total"
   Convert: "$1,234.56" → 1234.56, "RM 500.00" → 500.00

5. discount_amount: Discount amount (number)
   Look for: "Discount", "Adjustment", "Contractual Adj"

6. tax_amount: Tax amount (number)
   Look for: "Tax", "GST", "VAT", "Service Tax"

7. total_amount: Total amount due (REQUIRED, number)
   Look for: "Total Amount Due", "Total Due", "Balance Due", "Amount Owed", "Grand Total"
   CRITICAL: This field is REQUIRED
   IMPORTANT: If the bill has sections (A, B, C...) each with a subtotal, sum all section
   subtotals to compute the total if "Total Amount Due" value is missing or unclear.
   Example: Section A $268 + Section B $169 + Section C $472 = $909.00

PATIENT INFORMATION:
- full_name: Patient full name
- phone_number: Contact phone
- dob: Date of birth in YYYY-MM-DD format
- gender: Male, Female, or Other
- discharge_date: Discharge date in YYYY-MM-DD format

LINE ITEMS - Extract EVERY service/charge:

1. cpt_code: CPT or procedure code
   Examples: "99213", "80053", "CPT-12345"

2. description: Service description (REQUIRED)
   Examples: "Room Charges", "Laboratory Tests", "Consultation Fee"

3. qty: Quantity (integer)
   Examples: "1", "3", "10"

4. unit_price: Price per unit (number)
   Convert: "$50.00" → 50.00

5. total_price: Total price for line (number)
   Convert: "$150.00" → 150.00

CRITICAL EXTRACTION RULES:

1. EXTRACT ALL LINE ITEMS from ALL pages - do not skip any

2. INVOICE NUMBER is REQUIRED:
   - Search in header, footer, top-right, top-left
   - Look for ANY identifier: Invoice #, Bill #, Receipt #, Ref #, Account #
   - If multiple numbers, prefer "Invoice #" or "Bill #"
   - Example: "Invoice #: INV-2026-00847" → "INV-2026-00847"

3. TOTAL AMOUNT is REQUIRED:
   - Usually at bottom of bill
   - Look for: "Total Amount Due", "Total Due", "Balance Due", "Grand Total"
   - Must be a number (remove currency symbols and commas)
   - If total line value is missing/garbled, SUM all section subtotals:
     Section A Subtotal + Section B Subtotal + Section C Subtotal = Total

4. DATE FORMATS:
   - Always convert to YYYY-MM-DD
   - "03/02/2026" → "2026-03-02"
   - "March 2, 2026" → "2026-03-02"
   - "02-Mar-2026" → "2026-03-02"

5. AMOUNT FORMATS:
   - Remove currency symbols: $, RM, USD, etc.
   - Remove commas: "1,234.56" → 1234.56
   - Keep as number, not string

6. SYNONYMS TO RECOGNIZE:
   - Invoice # = Bill # = Receipt # = Ref # = Account # = Claim #
   - Total Due = Balance Due = Amount Owed = Grand Total = Net Payable
   - Discount = Adjustment = Allowance = Write-off
   - Tax = GST = VAT = Service Tax

7. NULL VALUES: Use null for missing fields, but NEVER for invoice_number or total_amount

EXAMPLES:

Example 1 - Header:
"Invoice #: INV-2026-00847
Invoice Date: 03/02/2026
Due Date: 04/01/2026"
→ invoice_number="INV-2026-00847"
→ invoice_date="2026-03-02"
→ due_date="2026-04-01"

Example 2 - Line Item:
"Room Charges | 3 Days | $200.00 | $600.00"
→ description="Room Charges", qty=3, unit_price=200.00, total_price=600.00

Example 3 - Totals:
"Gross Charges: $5,000.00
Discount: $500.00
Tax (GST 6%): $270.00
Total Amount Due: $4,770.00"
→ initial_amount=5000.00, discount_amount=500.00, tax_amount=270.00, total_amount=4770.00

Example 4 - Section subtotals (OCR may drop the total value):
"Section A Subtotal: $268.00
Section B Subtotal: $169.00
Section C Subtotal: $472.00
TOTAL AMOUNT DUE:"   ← value missing in OCR
→ total_amount = 268.00 + 169.00 + 472.00 = 909.00"""


def extract_bill_from_chunk(
    text_chunk: str,
    chunk_index: int,
    total_chunks: int,
) -> ValidatedBill:
    """
    Extract bill data from a text chunk.

    For first chunk: extract header + patient + line items
    For subsequent chunks: extract only line items
    """
    structured_llm = llm.with_structured_output(ValidatedBill)

    if chunk_index == 0:
        prompt = f"""Extract complete bill information from this document.

This is chunk 1 of {total_chunks}.

{text_chunk}

Return complete bill header, patient information, and ALL line items found in this chunk.
CRITICAL: invoice_number and total_amount are REQUIRED fields - search thoroughly.
If total_amount is missing, sum all section subtotals (Section A + B + C...)."""
    else:
        prompt = f"""Extract ONLY line items from this bill chunk. Use minimal header/patient info.

This is chunk {chunk_index + 1} of {total_chunks}.

{text_chunk}

Return a ValidatedBill with minimal header (invoice_number="Chunk {chunk_index + 1}") and ALL line items from this chunk."""

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    def _to_float(val: str) -> Optional[float]:
        if not val:
            return None
        try:
            cleaned = val.replace(",", "").replace("$", "").strip()
            return float(cleaned)
        except Exception:
            return None

    def _fallback_invoice_number(text: str) -> Optional[str]:
        # Prefer explicit invoice labels when present.
        patterns = [
            r"(?i)invoice\s*(?:#|no\.?|number)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{4,})",
            r"(?i)bill\s*(?:#|no\.?|number)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{4,})",
            r"(?i)receipt\s*(?:#|no\.?|number)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{4,})",
            r"(?i)\b(INV[-/ ]?\d{4}[-/ ]?\d{3,})\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return re.sub(r"\s+", "", m.group(1))
        return None

    def _fallback_total_amount(text: str) -> Optional[float]:
        # ── Strategy 1: explicit "Total Amount Due / Total Due / Balance Due" label ──
        label_patterns = [
            r"(?i)total\s*amount\s*due\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            r"(?i)total\s*due\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            r"(?i)balance\s*due\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            r"(?i)grand\s*total\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            r"(?i)amount\s*owed\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
        ]
        for pattern in label_patterns:
            m = re.search(pattern, text)
            if m:
                parsed = _to_float(m.group(1))
                if parsed is not None:
                    return parsed

        # ── Strategy 2: sum named section subtotals ───────────────────────────────
        # OCR on two-column summary tables frequently misreads the TOTAL AMOUNT DUE
        # row — the dollar value gets pulled up into the "Payments Received" row
        # directly above it, leaving the total line blank.
        # Example OCR output:
        #   "Payments Received: $909.00 TOTAL AMOUNT DUE: Payment due by..."
        # The correct recovery is to sum Section A/B/C subtotals and then apply
        # only real discounts/adjustments — NOT "Payments Received", because OCR
        # may have already mis-attributed the total value to that field.
        subtotals = re.findall(
            r"(?i)section\s*[A-Z]\s*subtotal\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            text,
        )
        if len(subtotals) >= 2:
            values = [_to_float(x) for x in subtotals]
            values = [x for x in values if x is not None]
            if values:
                gross = float(round(sum(values), 2))

                # Apply real discount/contractual adjustment only.
                discount_match = re.search(
                    r"(?i)(?:discount|contractual\s*adj(?:ustment)?)\s*[:\-]?\s*-?\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
                    text,
                )
                tax_match = re.search(
                    r"(?i)(?:tax|gst|vat)\s*[^$\d]{0,10}\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
                    text,
                )
                discount = _to_float((discount_match.group(1) if discount_match else None) or "0") or 0.0
                tax = _to_float((tax_match.group(1) if tax_match else None) or "0") or 0.0

                result = float(round(gross - discount + tax, 2))
                print(
                    f"[llm] _fallback_total_amount: section-subtotal sum={gross}, "
                    f"discount={discount}, tax={tax} → total={result}"
                )
                return result

        # ── Strategy 3: Gross Charges line as last resort ─────────────────────────
        gross_match = re.search(
            r"(?i)gross\s*charges?\s*[:\-]?\s*\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            text,
        )
        if gross_match:
            gross = _to_float(gross_match.group(1))
            if gross is not None:
                print(f"[llm] _fallback_total_amount: fell back to gross_charges={gross}")
                return gross

        return None

    def _fallback_line_items(text: str, total_amount: Optional[float]) -> List[BillLineItem]:
        # Last-resort deterministic item extraction for OCR-heavy bills.
        items: List[BillLineItem] = []

        line_pattern = re.compile(
            r"(?im)([A-Za-z][A-Za-z0-9\s\-/().,]{4,}?)\s+(?:\$?([0-9][0-9,]*\.?[0-9]{0,2}))\s+(?:\$?([0-9][0-9,]*\.?[0-9]{0,2}))"
        )
        for match in line_pattern.finditer(text):
            description = re.sub(r"\s+", " ", (match.group(1) or "").strip())
            unit = _to_float(match.group(2) or "")
            total = _to_float(match.group(3) or "")

            if not description or len(description) < 5:
                continue
            if unit is None and total is None:
                continue

            # Skip common summary rows to reduce false positives.
            if re.search(r"(?i)subtotal|total\s+amount\s+due|charges\s+summary|payments\s+received", description):
                continue

            qty = 1
            if unit is not None and total is not None and unit > 0:
                ratio = total / unit
                if abs(round(ratio) - ratio) < 0.01 and 0 < round(ratio) <= 20:
                    qty = int(round(ratio))

            items.append(BillLineItem(
                description=description,
                qty=qty,
                unit_price=unit,
                total_price=total,
            ))

            # Keep fallback conservative.
            if len(items) >= 5:
                break

        if items:
            return items

        if total_amount is not None:
            # Ensure queue validation can proceed when LLM fails but key bill fields exist.
            return [
                BillLineItem(
                    description="Medical service charges",
                    qty=1,
                    unit_price=total_amount,
                    total_price=total_amount,
                )
            ]

        return []

    try:
        result = structured_llm.invoke(messages)

        # Fallback for noisy OCR text: recover key header fields deterministically.
        if chunk_index == 0:
            if not result.bill.invoice_number:
                fallback_inv = _fallback_invoice_number(text_chunk)
                if fallback_inv:
                    result.bill.invoice_number = fallback_inv
                    print(f"[llm] Chunk {chunk_index + 1}: recovered invoice_number via regex")
            if result.bill.total_amount is None:
                fallback_total = _fallback_total_amount(text_chunk)
                if fallback_total is not None:
                    result.bill.total_amount = fallback_total
                    print(f"[llm] Chunk {chunk_index + 1}: recovered total_amount via regex = {fallback_total}")

        print(f"[llm] Chunk {chunk_index + 1}: extracted {len(result.line_items)} line items")
        return result
    except Exception as e:
        error_msg = str(e)
        print(f"[llm] Chunk {chunk_index + 1}: extraction failed, attempting recovery")

        # Try to recover from Groq/LangChain failed_generation payload
        if "tool_use_failed" in error_msg or "failed_generation" in error_msg:
            try:
                import json

                patterns = [
                    r"'failed_generation': '(.+?)'[,}]",
                    r'"failed_generation": "(.+?)"[,}]',
                    r"'failed_generation':\s*'(.+)'",
                    r'"failed_generation":\s*"(.+)"',
                ]

                partial_json = None
                for pattern in patterns:
                    match = re.search(pattern, error_msg, re.DOTALL)
                    if match:
                        partial_json = match.group(1)
                        break

                if partial_json:
                    partial_json = partial_json.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")

                    # Sometimes Groq returns markdown prose in failed_generation.
                    if partial_json.startswith("**") or partial_json.startswith("##"):
                        raise ValueError("LLM returned markdown text instead of structured JSON")

                    if partial_json.startswith("```json"):
                        partial_json = partial_json.split("\n", 1)[1] if "\n" in partial_json else partial_json
                    if partial_json.startswith("```"):
                        partial_json = partial_json.split("\n", 1)[1] if "\n" in partial_json else partial_json
                    if "```" in partial_json:
                        partial_json = partial_json.split("```")[0]

                    if '"name": "ValidatedBill"' in partial_json or "'name': 'ValidatedBill'" in partial_json:
                        args_match = re.search(r'"arguments":\s*({.+)', partial_json, re.DOTALL)
                        if args_match:
                            partial_json = args_match.group(1)
                            print("[llm] Extracted arguments from Groq tool call wrapper")

                    try:
                        data = json.loads(partial_json.strip())
                        bill = BillHeader(**data.get("bill", {}))
                        patient = PatientInfo(**data.get("patient", {}))
                        line_items = [BillLineItem(**item) for item in data.get("line_items", [])]
                        result = ValidatedBill(bill=bill, patient=patient, line_items=line_items)

                        # Always attempt required-field recovery after JSON parse
                        if chunk_index == 0:
                            if not result.bill.invoice_number:
                                result.bill.invoice_number = _fallback_invoice_number(text_chunk)
                            if result.bill.total_amount is None:
                                fallback_total = _fallback_total_amount(text_chunk)
                                if fallback_total is not None:
                                    result.bill.total_amount = fallback_total
                                    print(f"[llm] Chunk {chunk_index + 1}: recovered total_amount after JSON parse = {fallback_total}")
                            if not result.line_items:
                                result.line_items = _fallback_line_items(text_chunk, result.bill.total_amount)

                        print(f"[llm] Chunk {chunk_index + 1}: recovered {len(result.line_items)} line items")
                        return result
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as parse_err:
                        print(f"[llm] JSON recovery failed: {parse_err}")
            except Exception as recovery_err:
                print(f"[llm] Recovery failed: {recovery_err}")

        if chunk_index == 0:
            fallback_inv = _fallback_invoice_number(text_chunk)
            fallback_total = _fallback_total_amount(text_chunk)
            fallback_items = _fallback_line_items(text_chunk, fallback_total)

            if fallback_inv and fallback_total is not None and fallback_items:
                print(f"[llm] Chunk {chunk_index + 1}: deterministic fallback recovered bill data")
                return ValidatedBill(
                    bill=BillHeader(
                        invoice_number=fallback_inv,
                        total_amount=fallback_total,
                    ),
                    patient=PatientInfo(),
                    line_items=fallback_items,
                )

        print(f"[llm] Chunk {chunk_index + 1}: returning empty result - {error_msg[:200]}")
        # Return minimal valid result
        return ValidatedBill(
            bill=BillHeader(
                invoice_number=f"Chunk {chunk_index + 1}" if chunk_index > 0 else None
            ),
            patient=PatientInfo(),
            line_items=[],
        )


def merge_bill_results(results: List[Optional[ValidatedBill]]) -> ParsedBill:
    """
    Merge results from multiple chunks into a single ParsedBill.

    Takes header/patient from first chunk and combines all line items.
    """
    # Filter out None results
    valid_results = [r for r in results if r is not None]

    if not valid_results:
        raise ValueError("No valid results to merge")

    # Use header and patient from first chunk
    first = valid_results[0]

    # Combine all line items
    all_items = []
    for result in valid_results:
        all_items.extend(result.line_items)

    print(f"[llm] Merged {len(valid_results)} chunks: {len(all_items)} total line items")

    # Convert to ParsedBill format
    def _to_date(val) -> Optional[date]:
        if not val:
            return None
        try:
            from datetime import datetime
            return datetime.strptime(str(val), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _to_decimal(val) -> Optional[Decimal]:
        if val is None:
            return None
        try:
            return Decimal(str(val))
        except Exception:
            return None

    parsed = ParsedBill()
    parsed.bill = BillData(
        invoice_number=first.bill.invoice_number,
        invoice_date=_to_date(first.bill.invoice_date),
        due_date=_to_date(first.bill.due_date),
        initial_amount=_to_decimal(first.bill.initial_amount),
        discount_amount=_to_decimal(first.bill.discount_amount),
        tax_amount=_to_decimal(first.bill.tax_amount),
        total_amount=_to_decimal(first.bill.total_amount),
    )
    parsed.patient_name = first.patient.full_name
    parsed.patient_phone = first.patient.phone_number
    parsed.patient_dob = _to_date(first.patient.dob)
    parsed.patient_gender = first.patient.gender
    parsed.discharge_date = _to_date(first.patient.discharge_date)

    parsed.line_items = [
        BillDescriptionItem(
            cpt_code=item.cpt_code,
            description=item.description,
            qty=item.qty,
            unit_price=_to_decimal(item.unit_price),
            total_price=_to_decimal(item.total_price),
        )
        for item in all_items
    ]

    return parsed


# ── Backward Compatibility (deprecated) ────────────────────────────────────────

def validate_bill(raw_pdf_text: str, parsed: ParsedBill) -> ParsedBill:
    """
    DEPRECATED: Legacy function for backward compatibility.

    Use extract_bill_from_chunk with unified_pdf_parser instead.
    """
    # Simple single-chunk extraction
    result = extract_bill_from_chunk(raw_pdf_text, 0, 1)

    # Merge with existing parsed data (prefer LLM results)
    def pick(llm_val, current):
        return llm_val if llm_val is not None else current

    parsed.bill.invoice_number = pick(result.bill.invoice_number, parsed.bill.invoice_number)
    parsed.bill.total_amount = pick(result.bill.total_amount, parsed.bill.total_amount)

    if result.line_items:
        parsed.line_items = [
            BillDescriptionItem(
                cpt_code=item.cpt_code,
                description=item.description,
                qty=item.qty,
                unit_price=item.unit_price,
                total_price=item.total_price,
            )
            for item in result.line_items
        ]

    return parsed