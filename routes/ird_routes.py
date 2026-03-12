"""
routes/ird_routes.py
---------------------
POST /api/patient/{patient_id}/generate-ird

Generates an Insurance Ready Document (IRD) PDF for the given patient's
most recent discharge:
  - Fetches patient + discharge info, reports (with test results), bills
  - Runs ICD-10 RAG lookup on the clinical report data
  - Generates a formatted PDF via ReportLab
  - Uploads PDF to Cloudinary (folder: ird_documents/)
  - Returns the Cloudinary URL + metadata
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from models.discharge_history import DischargeHistory
from services.ird_service import generate_ird, generate_ird_pdf_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patient", tags=["IRD Generator"])


def _resolve_discharge_id(patient_id: int, db: Session) -> int:
    """Return the most recent discharge_id for patient_id, or raise 404."""
    discharge = (
        db.query(DischargeHistory)
        .filter(DischargeHistory.patient_id == patient_id)
        .order_by(DischargeHistory.created_at.desc())
        .first()
    )
    if not discharge:
        raise HTTPException(
            status_code=404,
            detail=f"No discharge record found for patient ID: {patient_id}",
        )
    return discharge.id


# ── Response schema ───────────────────────────────────────────────────────────

class ICDCodeItem(BaseModel):
    code: str
    title: str
    rationale: str


class IRDResponse(BaseModel):
    success: bool
    ird_url: str
    icd_codes: List[ICDCodeItem]
    icd_generation_failed: bool
    report_count: int
    bill_count: int
    patient_name: str
    discharge_date: Optional[str]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/{patient_id}/generate-ird",
    response_model=IRDResponse,
    summary="Generate Insurance Ready Document (IRD) PDF for a patient's latest discharge",
)
def generate_ird_endpoint(
    patient_id: int,
    db: Session = Depends(get_db),
):
    """
    Generates a PDF Insurance Ready Document for the given patient's most recent discharge.

    **Steps:**
    1. Resolves the latest discharge for the patient
    2. Loads patient, discharge, reports + test results, bills from DB
    3. Runs ICD-10 RAG lookup on report findings (non-blocking — PDF is still generated if this fails)
    4. Generates a formatted PDF with patient info, ICD codes, and links to report/bill PDFs
    5. Uploads PDF to Cloudinary (`ird_documents/` folder)
    6. Returns the secure Cloudinary URL + metadata

    **Error responses:**
    - `404` — patient not found, no discharge exists, or no clinical reports exist
    - `500` — PDF generation or Cloudinary upload failed
    """
    discharge_id = _resolve_discharge_id(patient_id, db)
    try:
        result = generate_ird(discharge_id, db)
        return result

    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404, detail=msg)

    except RuntimeError as exc:
        msg = str(exc)
        logger.error("IRD runtime error for patient %s / discharge %s: %s", patient_id, discharge_id, msg)
        raise HTTPException(status_code=500, detail=msg)

    except Exception as exc:
        logger.error("IRD Generation Error for patient %s / discharge %s: %s", patient_id, discharge_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate Insurance Ready Document",
        )


@router.get(
    "/{patient_id}/preview-ird",
    summary="Preview IRD PDF — downloads the PDF directly (no Cloudinary upload)",
    response_class=StreamingResponse,
)
def preview_ird_endpoint(
    patient_id: int,
    db: Session = Depends(get_db),
):
    """
    Generates the IRD PDF for the patient's most recent discharge and streams it
    directly to the browser/client as a download.
    Does **not** upload to Cloudinary — useful for testing and previewing.
    """
    discharge_id = _resolve_discharge_id(patient_id, db)
    try:
        pdf_bytes, patient_name = generate_ird_pdf_bytes(discharge_id, db)
        safe_name = patient_name.replace(" ", "_")
        filename = f"IRD_{patient_id}_{safe_name}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("IRD preview error for patient %s / discharge %s: %s", patient_id, discharge_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate IRD preview")
