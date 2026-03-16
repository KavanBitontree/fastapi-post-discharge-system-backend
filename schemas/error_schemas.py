"""
schemas/error_schemas.py
------------------------
Structured error response models for consistent API error handling.

All API errors return a standardized JSON structure with:
- error_code: Unique machine-readable identifier (e.g., BILL_DUPLICATE_INVOICE)
- message: User-friendly error description
- severity: error | warning | info
- context: Document-specific details (what broke, when, relevant IDs)
- action: Actionable guidance for the admin
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel


class ErrorContext(BaseModel):
    """Document-specific context about what went wrong."""
    document_type: Optional[str] = None      # bill | report | prescription
    filename: Optional[str] = None           # The uploaded file name
    discharge_id: Optional[int] = None       # Associated discharge
    patient_id: Optional[int] = None         # Associated patient
    invoice_number: Optional[str] = None     # For duplicate bill errors
    report_name: Optional[str] = None        # For duplicate report errors
    timestamp: Optional[str] = None          # ISO 8601 when error occurred
    additional: Optional[Dict[str, Any]] = None  # Any other relevant data


class StructuredErrorResponse(BaseModel):
    """
    Standard error response returned by all endpoints.
    
    Example:
    {
        "error_code": "BILL_DUPLICATE_INVOICE",
        "message": "Bill with invoice number 'INV-2024-001' already uploaded",
        "severity": "error",
        "context": {
            "document_type": "bill",
            "invoice_number": "INV-2024-001",
            "discharge_id": 42,
            "timestamp": "2026-03-13T10:30:45Z"
        },
        "action": "Remove the duplicate file and retry"
    }
    """
    error_code: str                          # Unique code for frontend handling
    message: str                             # Display to user
    severity: str = "error"                  # error | warning | info
    context: Optional[ErrorContext] = None   # Details about the error
    action: Optional[str] = None             # What the admin should do


# ── Error Code Catalog ─────────────────────────────────────────────────────────

ERROR_CODES = {
    # Bill-related errors
    "BILL_DUPLICATE_INVOICE": {
        "http_status": 409,
        "message_template": "Bill with invoice number '{invoice_number}' already uploaded on {timestamp}",
        "action": "Remove the duplicate file and retry with a different invoice"
    },
    "BILL_PARSE_ERROR": {
        "http_status": 422,
        "message_template": "Could not extract invoice data from the PDF",
        "action": "Verify the file is a valid hospital bill PDF and retry"
    },
    "BILL_MISSING_INVOICE_NUMBER": {
        "http_status": 422,
        "message_template": "No invoice number found in the PDF",
        "action": "Verify the file contains a complete invoice and retry"
    },
    "BILL_MISSING_TOTAL_AMOUNT": {
        "http_status": 422,
        "message_template": "No total amount found in the PDF",
        "action": "Verify the file contains billing information and retry"
    },
    "BILL_NO_LINE_ITEMS": {
        "http_status": 422,
        "message_template": "No line items found in the PDF",
        "action": "Verify the file contains itemized charges and retry"
    },

    # Report-related errors
    "REPORT_DUPLICATE": {
        "http_status": 409,
        "message_template": "Report '{report_name}' already exists for this discharge",
        "action": "Remove the duplicate report file and retry"
    },
    "REPORT_PARSE_ERROR": {
        "http_status": 422,
        "message_template": "Could not extract report data from the PDF",
        "action": "Verify the file is a valid medical lab report PDF and retry"
    },
    "REPORT_NO_DATA": {
        "http_status": 422,
        "message_template": "No lab test results found in the PDF",
        "action": "Verify the file contains test results and retry"
    },

    # Prescription-related errors
    "PRESCRIPTION_PARSE_ERROR": {
        "http_status": 422,
        "message_template": "Could not extract prescription data from the PDF",
        "action": "Verify the file is a valid prescription PDF and retry"
    },
    "PRESCRIPTION_NO_MEDICATIONS": {
        "http_status": 422,
        "message_template": "No medications found in the PDF",
        "action": "Verify the file contains medication information and retry"
    },

    # File-related errors
    "INVALID_FILE_FORMAT": {
        "http_status": 400,
        "message_template": "Only PDF files are accepted",
        "action": "Upload a valid PDF file and retry"
    },
    "FILE_TOO_LARGE": {
        "http_status": 413,
        "message_template": "File size exceeds the maximum limit",
        "action": "Upload a smaller file and retry"
    },

    # Discharge-related errors
    "DISCHARGE_NOT_FOUND": {
        "http_status": 404,
        "message_template": "Discharge record not found",
        "action": "Verify the discharge ID and retry"
    },
    "PATIENT_NOT_FOUND": {
        "http_status": 404,
        "message_template": "Patient not found or inactive",
        "action": "Verify the patient ID and ensure the patient is active"
    },

    # Service/Infrastructure errors
    "SERVICE_CLOUDINARY_ERROR": {
        "http_status": 503,
        "message_template": "Failed to upload file to cloud storage",
        "action": "Please retry in a moment. If the problem persists, contact support"
    },
    "SERVICE_LLM_TIMEOUT": {
        "http_status": 503,
        "message_template": "A temporary service error occurred while processing",
        "action": "Please retry in a moment. If the problem persists, contact support"
    },
    "SERVICE_UNAVAILABLE": {
        "http_status": 503,
        "message_template": "A backend service is temporarily unavailable",
        "action": "Please retry in a moment. If the problem persists, contact support"
    },

    # Generic errors
    "PROCESSING_ERROR": {
        "http_status": 500,
        "message_template": "An unexpected error occurred while processing the file",
        "action": "Please retry. If the problem persists, contact support with this timestamp: {timestamp}"
    },
}
