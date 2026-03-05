"""
LLM Bill Validator  —  LangChain/Groq-backed gap-filler
----------------------------------------------
Takes the raw PDF text and the Stage-1 :class:`ParsedBill` from
``parsers.bill_parser`` and asks the LLM to fill every ``None`` field,
resolve synonyms, and normalise dates / amounts.

Usage::

    from parsers.bill_parser import parse_bill_pdf, extract_raw_text
    from llm_validators.llm_bill_validator import validate_bill

    raw   = extract_raw_text("invoice.pdf")
    rough = parse_bill_pdf("invoice.pdf")
    final = validate_bill(raw, rough)            # ParsedBill, all fields populated
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from langsmith import traceable
from langchain_core.messages import SystemMessage, HumanMessage

from core.config import settings  # noqa: F401 — sets LangSmith os.environ vars
from core.llm_init import llm
from parsers.bill_parser import ParsedBill, BillData, BillDescriptionItem

# LLM bound to JSON mode — guarantees the response is a JSON object
_json_llm = llm.bind(response_format={"type": "json_object"})


def _parse_json(content: str) -> dict:
    """Strip optional markdown code fences then parse JSON."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]  # drop opening fence line
        content = content.rsplit("```", 1)[0]  # drop closing fence
    return json.loads(content.strip())

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """You are a medical-billing data-extraction specialist.
You are given raw text from a hospital discharge invoice / bill PDF and a
partial JSON object that a regex parser already extracted.  Your task is to
return a COMPLETE JSON object by:

1. Filling every null / missing field by reading the raw text.
2. Resolving common synonyms:
   - "Patient" can also appear as: Victim, Client, Member, Beneficiary, Patient Name, Insured, Subscriber
   - "Invoice Number" can also appear as: Bill No, Receipt #, Ref No, Claim #, Account #, Invoice No, Billing Ref
   - "Total Amount" can also appear as: Total Due, Balance Due, Amount Owed, Grand Total, Net Payable, Amount Due
   - "Discount" can also appear as: Adjustment, Allowance, Rebate, Write-off, Contractual Adjustment
   - "Tax" can also appear as: GST, VAT, Service Tax, Surcharge
   - "Invoice Date" can also appear as: Bill Date, Issue Date, Service Date, Date of Service
   - "Due Date" can also appear as: Payment Due Date, Pay By, Expiry Date, Final Payment Date
3. Normalising ALL dates to ISO format YYYY-MM-DD (e.g. "Jan 5, 2025" → "2025-01-05").
4. Normalising amounts to numeric floats (strip currency symbols, commas, etc.).
5. Setting any field to null if you genuinely cannot find the information.

Return ONLY the JSON object described below — no markdown, no explanation.

JSON schema:
{
  "bill": {
    "invoice_number": "string or null",
    "invoice_date":   "YYYY-MM-DD or null",
    "due_date":       "YYYY-MM-DD or null",
    "initial_amount": float or null,
    "discount_amount": float or null,
    "tax_amount":     float or null,
    "total_amount":   float or null
  },
  "patient": {
    "full_name":      "string or null",
    "email":          "string or null",
    "phone_number":   "string or null",
    "dob":            "YYYY-MM-DD or null",
    "gender":         "Male | Female | Other | null",
    "discharge_date": "YYYY-MM-DD or null"
  },
  "line_items": [
    {
      "cpt_code":    "string or null",
      "description": "string",
      "qty":         integer or null,
      "unit_price":  float or null,
      "total_price": float or null
    }
  ]
}
"""


def _user_prompt(raw_text: str, parsed: ParsedBill) -> str:
    hint = {
        "bill": {
            "invoice_number": parsed.bill.invoice_number,
            "invoice_date": str(parsed.bill.invoice_date) if parsed.bill.invoice_date else None,
            "due_date": str(parsed.bill.due_date) if parsed.bill.due_date else None,
            "initial_amount": float(parsed.bill.initial_amount) if parsed.bill.initial_amount else None,
            "discount_amount": float(parsed.bill.discount_amount) if parsed.bill.discount_amount else None,
            "tax_amount": float(parsed.bill.tax_amount) if parsed.bill.tax_amount else None,
            "total_amount": float(parsed.bill.total_amount) if parsed.bill.total_amount else None,
        },
        "patient": {
            "full_name": parsed.patient_name,
            "email": parsed.patient_email,
            "phone_number": parsed.patient_phone,
            "dob": str(parsed.patient_dob) if parsed.patient_dob else None,
            "gender": parsed.patient_gender,
            "discharge_date": str(parsed.discharge_date) if parsed.discharge_date else None,
        },
        "line_items": [
            {
                "cpt_code": item.cpt_code,
                "description": item.description,
                "qty": item.qty,
                "unit_price": float(item.unit_price) if item.unit_price else None,
                "total_price": float(item.total_price) if item.total_price else None,
            }
            for item in parsed.line_items
        ],
    }
    return (
        "=== RAW PDF TEXT ===\n"
        + raw_text
        + "\n\n=== PARTIAL PARSE (fill in the nulls) ===\n"
        + json.dumps(hint, indent=2)
    )


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

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
    except InvalidOperation:
        return None


def _merge(original: ParsedBill, llm_data: dict) -> ParsedBill:
    """Overwrite None fields in *original* with values from *llm_data*."""
    b = llm_data.get("bill", {})
    p = llm_data.get("patient", {})
    li = llm_data.get("line_items", [])

    def pick(current, llm_val):
        return current if current is not None else llm_val

    original.bill.invoice_number = pick(original.bill.invoice_number, b.get("invoice_number"))
    original.bill.invoice_date = pick(original.bill.invoice_date, _to_date(b.get("invoice_date")))
    original.bill.due_date = pick(original.bill.due_date, _to_date(b.get("due_date")))
    original.bill.initial_amount = pick(original.bill.initial_amount, _to_decimal(b.get("initial_amount")))
    original.bill.discount_amount = pick(original.bill.discount_amount, _to_decimal(b.get("discount_amount")))
    original.bill.tax_amount = pick(original.bill.tax_amount, _to_decimal(b.get("tax_amount")))
    original.bill.total_amount = pick(original.bill.total_amount, _to_decimal(b.get("total_amount")))

    original.patient_name = pick(original.patient_name, p.get("full_name"))
    original.patient_email = pick(original.patient_email, p.get("email"))
    original.patient_phone = pick(original.patient_phone, p.get("phone_number"))
    original.patient_dob = pick(original.patient_dob, _to_date(p.get("dob")))
    original.patient_gender = pick(original.patient_gender, p.get("gender"))
    original.discharge_date = pick(original.discharge_date, _to_date(p.get("discharge_date")))

    if li and len(li) >= len(original.line_items):
        original.line_items = [
            BillDescriptionItem(
                cpt_code=row.get("cpt_code"),
                description=row.get("description"),
                qty=row.get("qty"),
                unit_price=_to_decimal(row.get("unit_price")),
                total_price=_to_decimal(row.get("total_price")),
            )
            for row in li
        ]

    return original


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@traceable(name="validate_bill", run_type="llm")
def validate_bill(raw_pdf_text: str, parsed: ParsedBill) -> ParsedBill:
    """
    Stage-2 LLM validation.

    Sends *raw_pdf_text* plus the Stage-1 *parsed* result to the shared LLM
    and merges the response back into *parsed*, filling any ``None`` fields.

    Returns the mutated :class:`ParsedBill` object (same instance).
    """
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=_user_prompt(raw_pdf_text, parsed)),
    ]

    response = _json_llm.invoke(messages)
    llm_data = _parse_json(response.content)
    return _merge(parsed, llm_data)