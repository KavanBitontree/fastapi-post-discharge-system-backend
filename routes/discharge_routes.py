"""
routes/discharge_routes.py
---------------------------
POST /api/discharge/process                     → Upload all docs, process via queue, create discharge record
POST /api/discharge/{id}/retry                  → Resume from the failed file onward
GET  /api/discharge/{id}/status                 → Poll processing progress
GET  /api/discharge/{id}/pdfs                   → Get all generated PDF Cloudinary URLs
GET  /api/discharge/patient/{patient_id}/pdfs   → Get PDF URLs for a patient's latest discharge

Flow
----
1. Admin selects a patient  (frontend holds patient_id)
2. Admin attaches up to 15 reports (max 15 pages each), 5 bills (max 5 pages each),
   5 prescriptions (max 5 pages each) — all PDFs
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

import fitz  # pymupdf

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from core.database import get_db
from models.discharge_history import DischargeHistory
from models.patient import Patient
from services.discharge_service import DischargeResult, FileJob, run_discharge_queue, run_discharge_queue_in_background
from controllers.discharge_pdf_controller import DischargePdfController
from schemas.discharge_schemas import DischargePdfsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discharge", tags=["Discharge"])

# Per-type file count limits
MAX_REPORT_FILES = 15
MAX_BILL_FILES = 5
MAX_PRESCRIPTION_FILES = 5

# Per-type page count limits (reject single PDFs exceeding these)
MAX_REPORT_PAGES = 15
MAX_BILL_PAGES = 5
MAX_PRESCRIPTION_PAGES = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _validate_pdf_files(
    files: List[UploadFile],
    label: str,
    max_files: int,
    max_pages: int,
) -> None:
    if len(files) > max_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {max_files} {label} PDFs allowed per discharge.",
        )
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"All {label} files must be PDF. Got: {f.filename!r}",
            )
        # Read bytes to check page count, then reset cursor for later processing
        content = await f.read()
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            page_count = len(doc)
            doc.close()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse PDF '{f.filename}'. Ensure it is a valid PDF file.",
            )
        if page_count > max_pages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{label.capitalize()} PDF '{f.filename}' has {page_count} pages. "
                    f"Maximum allowed is {max_pages} page(s) per {label} PDF."
                ),
            )
        await f.seek(0)


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

@router.post("/process", status_code=status.HTTP_202_ACCEPTED)
async def process_discharge(
    background_tasks: BackgroundTasks,
    patient_id:    int              = Form(..., description="ID of the patient"),
    strategy:      str              = Form("auto", description="LLM extraction strategy: auto | text | vision"),
    reports:       List[UploadFile] = File(default=[], description="Up to 15 medical report PDFs (max 15 pages each)"),
    bills:         List[UploadFile] = File(default=[], description="Up to 5 bill PDFs (max 5 pages each)"),
    prescriptions: List[UploadFile] = File(default=[], description="Up to 5 prescription PDFs (max 5 pages each)"),
    db: Session = Depends(get_db),
):
    """
    Upload all discharge documents and kick off background processing.

    Returns 202 Accepted immediately with the discharge_id so the frontend
    can start polling GET /api/discharge/{id}/status for live progress.
    The queue processes: reports → bills → prescriptions (in order).
    Each file is committed individually — if one fails, previous ones are kept.
    """
    # ── Validate inputs ───────────────────────────────────────────────────────
    await _validate_pdf_files(reports,       "report",       MAX_REPORT_FILES,       MAX_REPORT_PAGES)
    await _validate_pdf_files(bills,         "bill",         MAX_BILL_FILES,         MAX_BILL_PAGES)
    await _validate_pdf_files(prescriptions, "prescription", MAX_PRESCRIPTION_FILES, MAX_PRESCRIPTION_PAGES)

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

    # ── Read all files into memory NOW (before the request closes) ────────────
    report_jobs       = await _read_jobs(reports,       "report",       0, strategy)
    bill_jobs         = await _read_jobs(bills,         "bill",         0, strategy)
    prescription_jobs = await _read_jobs(prescriptions, "prescription", 0, strategy)

    all_jobs: List[FileJob] = report_jobs + bill_jobs + prescription_jobs

    # ── Schedule background processing and return immediately ─────────────────
    background_tasks.add_task(run_discharge_queue_in_background, discharge.id, all_jobs)

    return {
        "discharge_id": discharge.id,
        "patient_id":   patient_id,
        "status":       "pending",
        "total": {
            "reports":       len(report_jobs),
            "bills":         len(bill_jobs),
            "prescriptions": len(prescription_jobs),
        },
    }


# ── POST /api/discharge/{discharge_id}/retry ──────────────────────────────────

@router.post("/{discharge_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_discharge(
    background_tasks: BackgroundTasks,
    discharge_id:  int              = ...,
    strategy:      str              = Form("auto"),
    reports:       List[UploadFile] = File(default=[], description="Remaining report PDFs (from failed index)"),
    bills:         List[UploadFile] = File(default=[], description="Remaining bill PDFs"),
    prescriptions: List[UploadFile] = File(default=[], description="Remaining prescription PDFs"),
    db: Session = Depends(get_db),
):
    """
    Retry a failed discharge process.

    Returns 202 Accepted immediately; processing continues in the background.
    Poll GET /api/discharge/{id}/status for live progress.
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

    await _validate_pdf_files(reports,       "report",       MAX_REPORT_FILES,       MAX_REPORT_PAGES)
    await _validate_pdf_files(bills,         "bill",         MAX_BILL_FILES,         MAX_BILL_PAGES)
    await _validate_pdf_files(prescriptions, "prescription", MAX_PRESCRIPTION_FILES, MAX_PRESCRIPTION_PAGES)

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

    # ── Schedule background processing and return immediately ─────────────────
    background_tasks.add_task(run_discharge_queue_in_background, discharge_id, all_jobs)

    return {
        "discharge_id": discharge_id,
        "patient_id":   discharge.patient_id,
        "status":       "processing",
        "total": {
            "reports":       discharge.processed_reports + len(report_jobs),
            "bills":         discharge.processed_bills + len(bill_jobs),
            "prescriptions": discharge.processed_prescriptions + len(prescription_jobs),
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


# ── GET /api/discharge/{discharge_id}/pdfs ────────────────────────────────────

@router.get("/{discharge_id}/pdfs", response_model=DischargePdfsResponse)
def get_discharge_pdfs(discharge_id: int, db: Session = Depends(get_db)):
    """
    Retrieve all generated PDF Cloudinary URLs for a specific discharge record.

    Returns:
    - **discharge_summary_url**: Cloudinary URL of the full hospital discharge summary PDF.
    - **patient_friendly_summary_url**: Cloudinary URL of the simplified patient-friendly report PDF.
    - **insurance_ready_url**: Cloudinary URL of the insurance-ready report PDF.

    Returns 404 if the discharge does not exist or no PDFs have been generated yet.
    """
    return DischargePdfController.get_pdfs_by_discharge(db, discharge_id)


# ── GET /api/discharge/patient/{patient_id}/pdfs ──────────────────────────────

@router.get("/patient/{patient_id}/pdfs", response_model=DischargePdfsResponse)
def get_patient_latest_discharge_pdfs(patient_id: int, db: Session = Depends(get_db)):
    """
    Retrieve PDF Cloudinary URLs for the **most recent** discharge record of a patient.

    Returns:
    - **discharge_summary_url**: Cloudinary URL of the full hospital discharge summary PDF.
    - **patient_friendly_summary_url**: Cloudinary URL of the simplified patient-friendly report PDF.
    - **insurance_ready_url**: Cloudinary URL of the insurance-ready report PDF.

    Returns 404 if no discharge record is found for the patient or no PDFs exist yet.
    """
    return DischargePdfController.get_pdfs_by_patient(db, patient_id)
