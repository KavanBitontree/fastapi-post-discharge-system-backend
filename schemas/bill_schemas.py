"""
Bill Pydantic Schemas
---------------------
Pydantic models for LLM-based bill extraction.
Used for structured output validation.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class BillLineItem(BaseModel):
    """Individual line item from a bill."""
    cpt_code: Optional[str] = Field(None, description="CPT/procedure code")
    description: str = Field(description="Service description")
    qty: Optional[int] = Field(None, description="Quantity")
    unit_price: Optional[float] = Field(None, description="Unit price")
    total_price: Optional[float] = Field(None, description="Total price")


class BillHeader(BaseModel):
    """Header information from a bill."""
    invoice_number: Optional[str] = Field(None, description="Invoice/bill number")
    invoice_date: Optional[str] = Field(None, description="Invoice date in YYYY-MM-DD")
    due_date: Optional[str] = Field(None, description="Due date in YYYY-MM-DD")
    initial_amount: Optional[float] = Field(None, description="Initial/gross amount")
    discount_amount: Optional[float] = Field(None, description="Discount amount")
    tax_amount: Optional[float] = Field(None, description="Tax amount")
    total_amount: Optional[float] = Field(None, description="Total amount due")


class PatientInfo(BaseModel):
    """Patient information from bill."""
    full_name: Optional[str] = Field(None, description="Patient full name")
    phone_number: Optional[str] = Field(None, description="Phone number")
    dob: Optional[str] = Field(None, description="Date of birth in YYYY-MM-DD")
    gender: Optional[str] = Field(None, description="Gender: Male, Female, Other")
    discharge_date: Optional[str] = Field(None, description="Discharge date in YYYY-MM-DD")


class ValidatedBill(BaseModel):
    """Complete validated bill."""
    bill: BillHeader
    patient: PatientInfo
    line_items: List[BillLineItem]
