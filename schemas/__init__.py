"""
Schemas Package
---------------
Pydantic schemas for LLM-based extraction and validation.

Organized by document type:
- report_schemas: Medical lab reports
- bill_schemas: Hospital bills and invoices
- prescription_schemas: Medical prescriptions
"""

from schemas.report_schemas import (
    TestResult,
    ReportHeader,
    ValidatedReport,
)

from schemas.bill_schemas import (
    BillLineItem,
    BillHeader,
    PatientInfo,
    ValidatedBill,
)

from schemas.prescription_schemas import (
    MedicationSchedule,
    MedicationRecurrence,
    Medication,
    PrescriptionHeader,
    ValidatedPrescription,
)

__all__ = [
    # Report schemas
    "TestResult",
    "ReportHeader",
    "ValidatedReport",
    # Bill schemas
    "BillLineItem",
    "BillHeader",
    "PatientInfo",
    "ValidatedBill",
    # Prescription schemas
    "MedicationSchedule",
    "MedicationRecurrence",
    "Medication",
    "PrescriptionHeader",
    "ValidatedPrescription",
]
