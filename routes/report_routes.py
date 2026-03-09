"""
Report Routes
-------------
API endpoints for uploading and processing medical report PDFs.
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from pathlib import Path
import shutil

from groq import RateLimitError as GroqRateLimitError
from core.database import get_db
from services.parsers.report_parser import extract_raw_text, is_scanned_pdf
from services.llm_validators.report_llm_validator import (
    extract_with_llm,
    extract_report_name_fallback,
    validate_extracted_report,
)
from services.db_store.report_store_db import (
    check_duplicate_report,
    pre_store_validate,
    store_report,
    ReportStoreError,
)


router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_report(
    file: UploadFile = File(..., description="PDF file of medical report"),
    patient_id: int = None,
    db: Session = Depends(get_db)
):
    """
    Upload a medical report PDF and process it.

    **Workflow:**
    1. Validate file + patient
    2. Save PDF to `public/pdfs/`
    3. Extract raw text (pdfplumber → pypdf fallback)
    4. Detect scanned PDF and warn if OCR needed
    5. Extract structured data via LLM
    6. Check for duplicates
    7. Store Report + ReportDescription rows in DB

    **Parameters:**
    - **file**: PDF file to upload (required)
    - **patient_id**: ID of the patient to link the report to (required)

    **Returns:**
    - report_id, report_name, patient_id, test_results_count, pdf_path
    """

    # ── Validate inputs ────────────────────────────────────────────────────
    if not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )

    if not patient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="patient_id is required"
        )

    # ── Verify patient exists ──────────────────────────────────────────────
    from models.patient import Patient
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient with id={patient_id} not found"
        )

    try:
        # ══════════════════════════════════════════════════════════════════
        # STEP 1: Read PDF bytes + save to disk
        # ══════════════════════════════════════════════════════════════════
        pdf_bytes = await file.read()

        pdf_dir = Path("public/pdfs")
        pdf_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        pdf_path = pdf_dir / safe_filename

        with pdf_path.open("wb") as buffer:
            buffer.write(pdf_bytes)

        # ══════════════════════════════════════════════════════════════════
        # STEP 2: Extract raw text
        # ══════════════════════════════════════════════════════════════════
        raw_text = extract_raw_text(pdf_bytes)

        # Warn if scanned — OCR pipeline not yet implemented
        # Route to AWS Textract / Google Document AI here in future
        scanned = is_scanned_pdf(pdf_bytes)
        if scanned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This appears to be a scanned PDF. OCR processing is not yet supported. Please upload a digital PDF."
            )

        # ══════════════════════════════════════════════════════════════════
        # STEP 3: LLM extraction  (raw text → structured data)
        # ══════════════════════════════════════════════════════════════════
        try:
            extracted = extract_with_llm(raw_text)
        except GroqRateLimitError as rle:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"AI service rate limit reached. Please try again later. ({rle})"
            )
        except Exception as llm_error:
            # LLM completely failed — try minimal fallback so we don't lose the PDF
            report_name = extract_report_name_fallback(raw_text)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"LLM extraction failed for report '{report_name}': {str(llm_error)}"
            )

        # ══════════════════════════════════════════════════════════════════
        # STEP 4: Filter non-medical content + pre-store validation
        # ══════════════════════════════════════════════════════════════════
        raw_test_count = len(extracted.test_results)

        # Remove demographics, metadata, duplicates — keep only medical data
        extracted = validate_extracted_report(extracted)

        if not extracted.header.report_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract report name from PDF"
            )

        if not extracted.test_results:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No medical test results found in PDF after filtering"
            )

        # Validate data integrity before writing to DB
        try:
            pre_store_validate(extracted)
        except ReportStoreError as ve:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Report validation failed: {ve}"
            )

        # ══════════════════════════════════════════════════════════════════
        # STEP 5: Duplicate check
        # ══════════════════════════════════════════════════════════════════
        is_duplicate = check_duplicate_report(
            db,
            patient_id=patient.id,
            report_name=extracted.header.report_name,
            report_date=extracted.header.report_date,
        )

        if is_duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Report '{extracted.header.report_name}' for this patient already exists"
            )

        # ══════════════════════════════════════════════════════════════════
        # STEP 6: Store in DB
        # ══════════════════════════════════════════════════════════════════
        report = store_report(
            db=db,
            extracted=extracted,
            patient_id=patient.id,
            report_url=f"/public/pdfs/{safe_filename}",
        )

        # ══════════════════════════════════════════════════════════════════
        # STEP 7: Response
        # ══════════════════════════════════════════════════════════════════
        return {
            "success": True,
            "message": "Report processed and stored successfully",
            "data": {
                "report_id":              report.id,
                "report_name":            report.report_name,
                "patient_id":             report.patient_id,
                "report_date":            report.report_date.isoformat() if report.report_date else None,
                "collection_date":        report.collection_date.isoformat() if report.collection_date else None,
                "status":                 report.status,
                "specimen_type":          report.specimen_type,
                "test_results_stored":    len(extracted.test_results),
                "test_results_extracted": raw_test_count,
                "pdf_path":               f"/public/pdfs/{safe_filename}",
                "file_size_bytes":        pdf_path.stat().st_size,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error processing report: {str(e)}"
        )
    finally:
        file.file.close()


@router.get("/test-services")
async def test_services():
    """Quick health check — verifies all report services import correctly."""
    from core.config import settings

    results = {"services": {}, "configuration": {}}

    for name, imports in {
        "report_parser":        "from services.parsers.report_parser import extract_raw_text, is_scanned_pdf",
        "report_llm_validator": "from services.llm_validators.report_llm_validator import extract_with_llm",
        "report_store_db":      "from services.db_store.report_store_db import check_duplicate_report, store_report",
    }.items():
        try:
            exec(imports)
            results["services"][name] = {"status": "OK"}
        except Exception as e:
            results["services"][name] = {"status": "ERROR", "error": str(e)}

    results["configuration"] = {
        "groq_api_key_set":    bool(settings.GROQ_API_KEY),
        "langsmith_tracing":   settings.LANGSMITH_TRACING,
        "langsmith_project":   settings.LANGSMITH_PROJECT,
        "database_connected":  True,
    }

    all_ok = all(s.get("status") == "OK" for s in results["services"].values())
    results["overall_status"] = "OK" if all_ok else "ERROR"

    return results