"""
store_bill.py  —  Orchestrator
-------------------------------
Pipeline:
  1. extract_raw_text   — get full plain text from the bill PDF
  2. parse_bill_pdf     — Stage-1 regex/table extraction → ParsedBill
  3. validate_bill      — Stage-2 Groq LLM fills every None field
  4. store_parsed_bill  — insert patient + bill + line items into DB

Usage::

    python store_bill.py                              # uses default PDF path
    python store_bill.py path/to/invoice.pdf
    python store_bill.py path/to/invoice.pdf https://cdn.example.com/bill.pdf
"""
import sys
import os
from decimal import Decimal
from typing import Optional

from parsers.bill_parser import parse_bill_pdf, extract_raw_text, ParsedBill
from llm_validators.llm_bill_validator import validate_bill


# ---------------------------------------------------------------------------
# DB store (moved here from test_bill_parse.py — identical logic)
# ---------------------------------------------------------------------------

def store_parsed_bill(parsed: ParsedBill, bill_url: Optional[str] = None) -> dict:
    """
    Persist a :class:`ParsedBill` into the database.

    Steps
    -----
    1. Look up the patient by email or phone; create one if not found.
    2. Insert a row into ``bills`` (skip if invoice_number already exists).
    3. Insert all line items into ``bill_description``.

    Returns
    -------
    dict with keys ``patient_id``, ``bill_id``, ``line_items_inserted``.
    """
    from core.database import SessionLocal
    from models.patient import Patient
    from models.bill import Bill
    from models.bill_description import BillDescription

    db = SessionLocal()
    try:
        # ── 1. Upsert patient ────────────────────────────────────────────────
        patient = None
        if parsed.patient_email:
            patient = db.query(Patient).filter(
                Patient.email == parsed.patient_email
            ).first()
        if patient is None and parsed.patient_phone:
            patient = db.query(Patient).filter(
                Patient.phone_number == parsed.patient_phone
            ).first()

        if patient is None:
            patient = Patient(
                full_name=parsed.patient_name,
                email=parsed.patient_email,
                phone_number=parsed.patient_phone,
                dob=parsed.patient_dob,
                gender=parsed.patient_gender,
                discharge_date=parsed.discharge_date,
                is_active=True,
            )
            db.add(patient)
            db.flush()
            print(f"  [+] Created patient  id={patient.id}  name={patient.full_name}")
        else:
            if parsed.discharge_date:
                patient.discharge_date = parsed.discharge_date
            print(f"  [~] Found patient    id={patient.id}  name={patient.full_name}")

        # ── 2. Insert bill ───────────────────────────────────────────────────
        existing_bill = db.query(Bill).filter(
            Bill.invoice_number == parsed.bill.invoice_number
        ).first()

        if existing_bill:
            print(f"  [!] Bill already exists  invoice={parsed.bill.invoice_number}  — skipping insert.")
            bill = existing_bill
            line_items_inserted = 0
        else:
            bill = Bill(
                patient_id=patient.id,
                invoice_number=parsed.bill.invoice_number,
                invoice_date=parsed.bill.invoice_date,
                due_date=parsed.bill.due_date,
                initial_amount=parsed.bill.initial_amount,
                discount_amount=parsed.bill.discount_amount or Decimal("0.00"),
                tax_amount=parsed.bill.tax_amount or Decimal("0.00"),
                total_amount=parsed.bill.total_amount,
                bill_url=bill_url,
            )
            db.add(bill)
            db.flush()
            print(f"  [+] Created bill     id={bill.id}  invoice={bill.invoice_number}")

            # ── 3. Insert line items ─────────────────────────────────────────
            items = [
                BillDescription(
                    bill_id=bill.id,
                    patient_id=patient.id,
                    cpt_code=item.cpt_code,
                    description=item.description,
                    qty=item.qty or 1,
                    unit_price=item.unit_price,
                    total_price=item.total_price,
                )
                for item in parsed.line_items
            ]
            db.bulk_save_objects(items)
            line_items_inserted = len(items)
            print(f"  [+] Inserted {line_items_inserted} bill_description rows")

        db.commit()
        return {
            "patient_id": patient.id,
            "bill_id": bill.id,
            "line_items_inserted": line_items_inserted if not existing_bill else 0,
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Public pipeline entry-point
# ---------------------------------------------------------------------------

def process_bill_pdf(pdf_path: str, bill_url: Optional[str] = None) -> dict:
    """
    Full pipeline: extract → parse → LLM validate → store.

    Parameters
    ----------
    pdf_path : str
        Path to the bill PDF file.
    bill_url : str, optional
        Public URL to associate with the bill record (e.g. cloud storage link).

    Returns
    -------
    dict with ``patient_id``, ``bill_id``, ``line_items_inserted``.
    """
    print("Step 1/3  Extracting raw text …")
    raw_text = extract_raw_text(pdf_path)

    print("Step 2/3  Stage-1 regex parse …")
    parsed = parse_bill_pdf(pdf_path)

    print("Step 3/3  Stage-2 LLM validation (Groq) …")
    parsed = validate_bill(raw_text, parsed)

    print("Storing to DB …")
    return store_parsed_bill(parsed, bill_url=bill_url)


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
    _DEFAULT_PDF = os.path.join(_PROJECT_ROOT, "public", "Medicare_Discharge_Final_Bill_(2).pdf")
    PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(_DEFAULT_PDF)
    BILL_URL = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"\nProcessing bill PDF: {PDF_PATH}\n")
    result = process_bill_pdf(PDF_PATH, bill_url=BILL_URL)

    print()
    print("Done!")
    print(f"  patient_id          : {result['patient_id']}")
    print(f"  bill_id             : {result['bill_id']}")
    print(f"  line_items_inserted : {result['line_items_inserted']}")
