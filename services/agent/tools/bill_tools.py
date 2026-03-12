"""
services/agent/tools/bill_tools.py
------------------------------------
SQLAlchemy-based tools for the Bills specialist node.
"""

from __future__ import annotations
from datetime import date as date_type
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from models.bill import Bill
from models.bill_description import BillDescription


def _bill_header(b: Bill, today: date_type) -> str:
    """Render all Bill columns including overdue status."""
    inv_date = b.invoice_date.strftime("%d %b %Y") if b.invoice_date else "N/A"
    if b.due_date:
        due_str = b.due_date.strftime("%d %b %Y")
        overdue = " [OVERDUE]" if b.due_date < today else ""
    else:
        due_str = "No due date"
        overdue = ""
    return (
        f"Invoice #{b.invoice_number}{overdue}\n"
        f"  Invoice date  : {inv_date}\n"
        f"  Due date      : {due_str}\n"
        f"  Initial amount: \u20b9{b.initial_amount}\n"
        f"  Discount      : \u20b9{b.discount_amount or 0}\n"
        f"  Tax           : \u20b9{b.tax_amount or 0}\n"
        f"  Total amount  : \u20b9{b.total_amount}"
    )


def _bill_line(d: BillDescription) -> str:
    """Render all BillDescription columns as a single line."""
    cpt = f"CPT: {d.cpt_code} | " if d.cpt_code else "CPT: N/A | "
    desc = d.description or "Service"
    return (
        f"  \u2022 {desc} | {cpt}"
        f"Qty: {d.qty} \u00d7 \u20b9{d.unit_price} = \u20b9{d.total_price}"
    )


def build_bill_tools(discharge_id: int, db: Session) -> list:

    @tool
    def get_all_bills() -> str:
        """
        Get a summary of all bills/invoices for the patient.
        Use when patient asks 'show my bills', 'what do I owe?', 'my invoices'.
        """
        bills = (
            db.query(Bill)
            .filter(Bill.discharge_id == discharge_id)
            .order_by(Bill.invoice_date.desc())
            .all()
        )
        if not bills:
            return "No bills found for this patient."

        today = date_type.today()
        lines = []
        for b in bills:
            inv_date = b.invoice_date.strftime("%d %b %Y") if b.invoice_date else "N/A"
            if b.due_date:
                due_str = b.due_date.strftime("%d %b %Y")
                overdue = " [OVERDUE]" if b.due_date < today else ""
            else:
                due_str = "No due date"
                overdue = ""
            lines.append(
                f"• Invoice #{b.invoice_number}{overdue} | Date: {inv_date} "
                f"| Initial: \u20b9{b.initial_amount} | Discount: \u20b9{b.discount_amount or 0} "
                f"| Tax: \u20b9{b.tax_amount or 0} | Total: \u20b9{b.total_amount} | Due: {due_str}"
            )
        return "Patient's bills:\n" + "\n".join(lines)

    @tool
    def get_bill_details(invoice_number: str) -> str:
        """
        Get full breakdown of a specific bill by invoice number.
        Use when patient asks about a specific invoice.

        Args:
            invoice_number: The invoice number string (e.g. 'INV-001')
        """
        bill = (
            db.query(Bill)
            .filter(
                Bill.discharge_id == discharge_id,
                Bill.invoice_number == invoice_number,
            )
            .first()
        )
        if not bill:
            return f"No bill with invoice number '{invoice_number}' found."

        today = date_type.today()
        lines = [_bill_header(bill, today), "", "Line items:"]
        descs = db.query(BillDescription).filter(BillDescription.bill_id == bill.id).all()
        if descs:
            for d in descs:
                lines.append(_bill_line(d))
        else:
            lines.append("  No line items on record.")
        return "\n".join(lines)

    @tool
    def get_total_outstanding() -> str:
        """
        Calculate total outstanding balance across all bills.
        Use when patient asks 'how much do I owe in total?' or 'total dues'.
        """
        bills = (
            db.query(Bill)
            .filter(Bill.discharge_id == discharge_id)
            .order_by(Bill.invoice_date.desc())
            .all()
        )
        if not bills:
            return "No bills found."

        today = date_type.today()
        total = sum(float(b.total_amount) for b in bills)
        lines = [f"Total outstanding across {len(bills)} invoice(s): \u20b9{total:.2f}", "", "Per-bill breakdown:"]
        for b in bills:
            inv_date = b.invoice_date.strftime("%d %b %Y") if b.invoice_date else "N/A"
            if b.due_date:
                due_str = b.due_date.strftime("%d %b %Y")
                overdue = " [OVERDUE]" if b.due_date < today else ""
            else:
                due_str = "No due date"
                overdue = ""
            lines.append(
                f"  • Invoice #{b.invoice_number}{overdue} | Date: {inv_date} "
                f"| Total: \u20b9{b.total_amount} | Due: {due_str}"
            )
        return "\n".join(lines)

    @tool
    def get_latest_bill() -> str:
        """
        Get the most recent bill with full line items.
        Use when patient asks 'what is my latest bill?' or 'recent invoice'.
        """
        bill = (
            db.query(Bill)
            .filter(Bill.discharge_id == discharge_id)
            .order_by(Bill.invoice_date.desc())
            .first()
        )
        if not bill:
            return "No bills found."

        today = date_type.today()
        lines = [f"Latest bill:", _bill_header(bill, today), "", "Line items:"]
        descs = db.query(BillDescription).filter(BillDescription.bill_id == bill.id).all()
        if descs:
            for d in descs:
                lines.append(_bill_line(d))
        else:
            lines.append("  No line items on record.")
        return "\n".join(lines)

    @tool
    def get_all_bill_data() -> str:
        """
        Get the COMPLETE billing history for the patient — every bill with every line item.
        Use this when you need a full financial overview or the patient asks about their
        complete billing history, total charges, or all invoice details at once.
        """
        bills = (
            db.query(Bill)
            .filter(Bill.discharge_id == discharge_id)
            .order_by(Bill.invoice_date.desc())
            .all()
        )
        if not bills:
            return "No billing records found for this patient."

        today = date_type.today()
        sections = []
        for b in bills:
            header = _bill_header(b, today)
            descs = db.query(BillDescription).filter(BillDescription.bill_id == b.id).all()
            if descs:
                items = "\n".join(_bill_line(d) for d in descs)
                sections.append(header + "\n  Line items:\n" + items)
            else:
                sections.append(header + "\n  No line items.")

        total = sum(float(b.total_amount) for b in bills)
        summary = f"Grand total across {len(bills)} invoice(s): \u20b9{total:.2f}"
        return "=== Complete Billing History ===\n\n" + "\n\n".join(sections) + f"\n\n{summary}"

    return [get_all_bills, get_bill_details, get_total_outstanding, get_latest_bill, get_all_bill_data]