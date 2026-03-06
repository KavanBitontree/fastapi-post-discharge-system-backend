"""
LLM Bill Validator
------------------
Pure LLM-based extraction of bill data with dynamic chunking support.

Unified extraction flow matching reports and prescriptions.
"""

from typing import Optional, List
from datetime import date
from decimal import Decimal

from core.txt_to_txt_llm_init import llm
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
→ initial_amount=5000.00, discount_amount=500.00, tax_amount=270.00, total_amount=4770.00"""


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
CRITICAL: invoice_number and total_amount are REQUIRED fields - search thoroughly."""
    else:
        prompt = f"""Extract ONLY line items from this bill chunk. Use minimal header/patient info.

This is chunk {chunk_index + 1} of {total_chunks}.

{text_chunk}

Return a ValidatedBill with minimal header (invoice_number="Chunk {chunk_index + 1}") and ALL line items from this chunk."""
    
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    
    try:
        result = structured_llm.invoke(messages)
        print(f"[llm] Chunk {chunk_index + 1}: extracted {len(result.line_items)} line items")
        return result
    except Exception as e:
        error_msg = str(e)
        print(f"[llm] Chunk {chunk_index + 1}: extraction failed, attempting recovery")
        
        # Try to recover from markdown-wrapped JSON
        if "failed_generation" in error_msg:
            try:
                import re
                import json
                
                # Extract the failed generation
                match = re.search(r"'failed_generation': '(.+?)'(?:,|})", error_msg, re.DOTALL)
                if not match:
                    match = re.search(r'"failed_generation": "(.+?)"(?:,|})', error_msg, re.DOTALL)
                
                if match:
                    partial_json = match.group(1)
                    # Clean up escape sequences
                    partial_json = partial_json.replace("\\n", "\n").replace('\\"', '"')
                    
                    # Remove markdown code fences if present
                    if partial_json.startswith("```json"):
                        partial_json = partial_json.split("\n", 1)[1]
                    if partial_json.startswith("```"):
                        partial_json = partial_json.split("\n", 1)[1]
                    if "```" in partial_json:
                        partial_json = partial_json.split("```")[0]
                    
                    # Try to parse as JSON
                    try:
                        data = json.loads(partial_json.strip())
                        
                        # Convert to ValidatedBill
                        bill = BillHeader(**data.get("bill", {}))
                        patient = PatientInfo(**data.get("patient", {}))
                        line_items = [BillLineItem(**item) for item in data.get("line_items", [])]
                        
                        result = ValidatedBill(bill=bill, patient=patient, line_items=line_items)
                        print(f"[llm] Chunk {chunk_index + 1}: recovered {len(result.line_items)} line items")
                        return result
                    except (json.JSONDecodeError, KeyError, TypeError) as parse_err:
                        print(f"[llm] JSON recovery failed: {parse_err}")
            except Exception as recovery_err:
                print(f"[llm] Recovery failed: {recovery_err}")
        
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
        except:
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