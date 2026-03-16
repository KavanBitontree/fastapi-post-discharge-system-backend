"""
core/error_handler.py
---------------------
Helper functions for creating structured error responses.

Maps error codes to HTTP status codes and creates consistent
StructuredErrorResponse objects for all API errors.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import HTTPException, status

from schemas.error_schemas import StructuredErrorResponse, ErrorContext, ERROR_CODES


def create_error_response(
    error_code: str,
    message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    action: Optional[str] = None,
    http_status: Optional[int] = None,
) -> tuple[StructuredErrorResponse, int]:
    """
    Create a structured error response from an error code.
    
    Parameters
    ----------
    error_code : str
        Unique error identifier (e.g., 'BILL_DUPLICATE_INVOICE')
    message : str, optional
        Override the default error message
    context : dict, optional
        Document-specific context (will be merged with defaults)
    action : str, optional
        Override the default action/guidance
    http_status : int, optional
        Override the default HTTP status code
        
    Returns
    -------
    tuple[StructuredErrorResponse, int]
        - StructuredErrorResponse object
        - HTTP status code
    """
    if error_code not in ERROR_CODES:
        # Fallback for unknown error codes
        return (
            StructuredErrorResponse(
                error_code=error_code,
                message=message or "An unexpected error occurred",
                severity="error",
                context=ErrorContext(timestamp=datetime.utcnow().isoformat() + "Z") if context else None,
                action=action or "Please contact support"
            ),
            http_status or 500
        )
    
    error_def = ERROR_CODES[error_code]
    final_status = http_status or error_def.get("http_status", 500)
    
    # Use provided message or template
    if not message:
        template = error_def.get("message_template", "")
        if context:
            try:
                message = template.format(**context)
            except KeyError:
                message = template
        else:
            message = template
    
    # Use provided action or default
    if not action:
        action = error_def.get("action", "Please contact support")
    
    # Build context with timestamp
    error_context = None
    if context or error_code.startswith(("BILL_", "REPORT_", "PRESCRIPTION_")):
        error_context = ErrorContext(
            timestamp=datetime.utcnow().isoformat() + "Z",
            **(context or {})
        )
    
    return (
        StructuredErrorResponse(
            error_code=error_code,
            message=message,
            severity="error",
            context=error_context,
            action=action
        ),
        final_status
    )


def raise_structured_error(
    error_code: str,
    message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    action: Optional[str] = None,
    http_status: Optional[int] = None,
) -> None:
    """
    Raise a FastAPI HTTPException with a structured error response.
    
    This wraps create_error_response and raises the appropriate HTTPException.
    """
    error_response, status_code = create_error_response(
        error_code=error_code,
        message=message,
        context=context,
        action=action,
        http_status=http_status,
    )
    
    raise HTTPException(
        status_code=status_code,
        detail=error_response.model_dump(exclude_none=True)
    )


# ── Specific error builders for common scenarios ────────────────────────────────

def error_duplicate_bill(invoice_number: str, discharge_id: int, filename: str) -> None:
    """Raise duplicate bill invoice error."""
    raise_structured_error(
        error_code="BILL_DUPLICATE_INVOICE",
        context={
            "document_type": "bill",
            "invoice_number": invoice_number,
            "discharge_id": discharge_id,
            "filename": filename,
        }
    )


def error_duplicate_report(report_name: str, discharge_id: int, filename: str) -> None:
    """Raise duplicate report error."""
    raise_structured_error(
        error_code="REPORT_DUPLICATE",
        context={
            "document_type": "report",
            "report_name": report_name,
            "discharge_id": discharge_id,
            "filename": filename,
        }
    )


def error_bill_parse(discharge_id: int, filename: str) -> None:
    """Raise bill parsing error."""
    raise_structured_error(
        error_code="BILL_PARSE_ERROR",
        context={
            "document_type": "bill",
            "discharge_id": discharge_id,
            "filename": filename,
        }
    )


def error_bill_missing_invoice_number(discharge_id: int, filename: str) -> None:
    """Raise error for missing invoice number."""
    raise_structured_error(
        error_code="BILL_MISSING_INVOICE_NUMBER",
        context={
            "document_type": "bill",
            "discharge_id": discharge_id,
            "filename": filename,
        }
    )


def error_bill_missing_total_amount(discharge_id: int, filename: str) -> None:
    """Raise error for missing total amount."""
    raise_structured_error(
        error_code="BILL_MISSING_TOTAL_AMOUNT",
        context={
            "document_type": "bill",
            "discharge_id": discharge_id,
            "filename": filename,
        }
    )


def error_bill_no_line_items(discharge_id: int, filename: str) -> None:
    """Raise error for missing line items."""
    raise_structured_error(
        error_code="BILL_NO_LINE_ITEMS",
        context={
            "document_type": "bill",
            "discharge_id": discharge_id,
            "filename": filename,
        }
    )


def error_invalid_file_format(filename: str) -> None:
    """Raise error for invalid file format."""
    raise_structured_error(
        error_code="INVALID_FILE_FORMAT",
        context={
            "filename": filename,
        }
    )


def error_discharge_not_found(discharge_id: int) -> None:
    """Raise error for discharge not found."""
    raise_structured_error(
        error_code="DISCHARGE_NOT_FOUND",
        context={
            "discharge_id": discharge_id,
        }
    )


def error_patient_not_found(patient_id: int) -> None:
    """Raise error for patient not found."""
    raise_structured_error(
        error_code="PATIENT_NOT_FOUND",
        context={
            "patient_id": patient_id,
        }
    )


def error_service_cloudinary(detail: str, discharge_id: Optional[int] = None) -> None:
    """Raise error for Cloudinary upload failure."""
    raise_structured_error(
        error_code="SERVICE_CLOUDINARY_ERROR",
        message=f"Failed to upload file to cloud storage: {detail}",
        context={
            "discharge_id": discharge_id,
        } if discharge_id else None
    )


def error_service_llm(detail: str, discharge_id: Optional[int] = None) -> None:
    """Raise error for LLM/parsing service failure."""
    raise_structured_error(
        error_code="SERVICE_LLM_TIMEOUT",
        message=f"A temporary service error occurred: {detail}",
        context={
            "discharge_id": discharge_id,
        } if discharge_id else None
    )


def error_processing(detail: str, discharge_id: Optional[int] = None) -> None:
    """Raise generic processing error."""
    raise_structured_error(
        error_code="PROCESSING_ERROR",
        message=f"An unexpected error occurred: {detail}",
        context={
            "discharge_id": discharge_id,
        } if discharge_id else None
    )
