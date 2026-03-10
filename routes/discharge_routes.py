"""
routes/discharge_routes.py
---------------------------
POST /api/discharge/process         → Upload all docs, process via queue, create discharge record
POST /api/discharge/{id}/retry      → Resume from the failed file onward
GET  /api/discharge/{id}/status     → Poll processing progress

Flow
----
1. Admin selects a patient  (frontend holds patient_id)
2. Admin attaches up to 5 reports, 5 bills, 5 prescriptions (all PDFs)
3. Admin clicks "Process" → POST /api/discharge/process
4. Backend creates a discharge_history row (status=pending), then runs the
   sequential queue.  Each file is committed individually on success.
5. If ALL succeed  → discharge.status = "completed"  → 201 response
6. If ANY fails    → discharge.status = "failed"     → 422 with progress info
7. Admin retries   → POST /api/discharge/{id}/retry  with remaining files
   The server resumes from the next unprocessed index (reads progress from DB).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from core.database import get_db
from models.discharge_history import DischargeHistory
from models.patient import Patient
from services.discharge_service import DischargeResult, FileJob, run_discharge_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discharge", tags=["Discharge"])

MAX_FILES_PER_TYPE = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_pdf_files(files: List[UploadFile], label: str) -> None:
    if len(files) > MAX_FILES_PER_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_FILES_PER_TYPE} {label} PDFs allowed per discharge.",
        )
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"All {label} files must be PDF. Got: {f.filename!r}",
            )


async def _read_jobs(
    files: List[UploadFile],
    doc_type: str,
    start_index: int,
    strategy: str,
) -> List[FileJob]:
    """Read uploaded files into memory and build FileJob descriptors."""
    jobs: List[FileJob] = []
    for i, f in enumerate(files, start=start_index):
        content = await f.read()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{Path(f.filename).name}"
        jobs.append(FileJob(
            doc_type=doc_type,
            index=i,
            filename=filename,
            content=content,
            strategy=strategy,
        ))
    return jobs


def _result_to_error_detail(result: DischargeResult) -> dict:
    return {
        "message": (
            "Processing stopped at a failed file. "
            "Already-stored documents will NOT be re-processed on retry. "
            "Re-upload only the failed file and any that follow it."
        ),
        "discharge_id": result.discharge_id,
        "status": result.status,
        "progress": {
            "processed_reports":       result.processed_reports,
            "processed_bills":         result.processed_bills,
            "processed_prescriptions": result.processed_prescriptions,
        },
        "failed_at": {
            "type":  result.failed_at_type,
            "index": result.failed_at_index,
        },
        "error": result.error,
    }


# ── POST /api/discharge/process ───────────────────────────────────────────────

@router.post("/process", status_code=status.HTTP_201_CREATED)
async def process_discharge(
    patient_id:    int              = Form(..., description="ID of the patient"),
    strategy:      str              = Form("auto", description="LLM extraction strategy: auto | text | vision"),
    reports:       List[UploadFile] = File(default=[], description="Up to 5 medical report PDFs"),
    bills:         List[UploadFile] = File(default=[], description="Up to 5 bill PDFs"),
    prescriptions: List[UploadFile] = File(default=[], description="Up to 5 prescription PDFs"),
    db: Session = Depends(get_db),
):
    """
    Upload all discharge documents and process them in a single request.

    The queue processes: reports → bills → prescriptions (in order).
    Each file is committed individually — if one fails, previous ones are kept.

    Returns discharge_id on both success and failure so the frontend can
    track the record and send a retry request.
    """
    # ── Validate inputs ───────────────────────────────────────────────────────
    _validate_pdf_files(reports,       "report")
    _validate_pdf_files(bills,         "bill")
    _validate_pdf_files(prescriptions, "prescription")

    if not reports and not bills and not prescriptions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one document must be uploaded.",
        )

    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.is_active == True,
    ).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient id={patient_id} not found or inactive.",
        )

    # ── Create discharge record ───────────────────────────────────────────────
    discharge = DischargeHistory(patient_id=patient_id, status="pending")
    db.add(discharge)
    db.commit()
    db.refresh(discharge)
    logger.info("Created discharge id=%d for patient id=%d", discharge.id, patient_id)

    # ── Read all files into memory and build the job queue ────────────────────
    report_jobs       = await _read_jobs(reports,       "report",       0, strategy)
    bill_jobs         = await _read_jobs(bills,         "bill",         0, strategy)
    prescription_jobs = await _read_jobs(prescriptions, "prescription", 0, strategy)

    all_jobs: List[FileJob] = report_jobs + bill_jobs + prescription_jobs

    # ── Run the sequential queue ──────────────────────────────────────────────
    result = run_discharge_queue(db, discharge, all_jobs)

    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_result_to_error_detail(result),
        )

    return {
        "discharge_id": result.discharge_id,
        "patient_id":   patient_id,
        "status":       result.status,
        "processed": {
            "reports":       result.processed_reports,
            "bills":         result.processed_bills,
            "prescriptions": result.processed_prescriptions,
        },
    }


# ── POST /api/discharge/{discharge_id}/retry ──────────────────────────────────

@router.post("/{discharge_id}/retry")
async def retry_discharge(
    discharge_id:  int              = ...,
    strategy:      str              = Form("auto"),
    reports:       List[UploadFile] = File(default=[], description="Remaining report PDFs (from failed index)"),
    bills:         List[UploadFile] = File(default=[], description="Remaining bill PDFs"),
    prescriptions: List[UploadFile] = File(default=[], description="Remaining prescription PDFs"),
    db: Session = Depends(get_db),
):
    """
    Retry a failed discharge process.

    Upload only the files that have NOT yet been processed.
    The server reads the progress counters from the DB to know the correct
    starting index — files are indexed correctly for idempotent duplicate checks.
    """
    discharge = db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first()
    if not discharge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discharge id={discharge_id} not found.",
        )
    if discharge.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discharge is already completed — nothing to retry.",
        )

    _validate_pdf_files(reports,       "report")
    _validate_pdf_files(bills,         "bill")
    _validate_pdf_files(prescriptions, "prescription")

    # Resume indices from stored progress
    report_jobs       = await _read_jobs(reports,       "report",       discharge.processed_reports,       strategy)
    bill_jobs         = await _read_jobs(bills,         "bill",         discharge.processed_bills,         strategy)
    prescription_jobs = await _read_jobs(prescriptions, "prescription", discharge.processed_prescriptions, strategy)

    all_jobs: List[FileJob] = report_jobs + bill_jobs + prescription_jobs

    if not all_jobs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files submitted for retry.",
        )

    result = run_discharge_queue(db, discharge, all_jobs)

    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_result_to_error_detail(result),
        )

    return {
        "discharge_id": result.discharge_id,
        "patient_id":   discharge.patient_id,
        "status":       result.status,
        "processed": {
            "reports":       result.processed_reports,
            "bills":         result.processed_bills,
            "prescriptions": result.processed_prescriptions,
        },
    }


# ── GET /api/discharge/{discharge_id}/status ──────────────────────────────────

@router.get("/{discharge_id}/status")
def get_discharge_status(discharge_id: int, db: Session = Depends(get_db)):
    """Poll the processing progress of a discharge record."""
    discharge = db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first()
    if not discharge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discharge id={discharge_id} not found.",
        )
    return {
        "discharge_id":   discharge.id,
        "patient_id":     discharge.patient_id,
        "discharge_date": discharge.discharge_date,
        "status":         discharge.status,
        "processed": {
            "reports":       discharge.processed_reports,
            "bills":         discharge.processed_bills,
            "prescriptions": discharge.processed_prescriptions,
        },
    }
