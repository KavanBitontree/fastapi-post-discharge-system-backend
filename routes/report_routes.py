"""
report_routes.py
----------------
API endpoints for uploading and processing medical report PDFs using LLM-first extraction.
"""

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path
import shutil
import logging
from datetime import datetime

from core.database import get_db
from services.parsers.report_parser import parse_pdf
from services.db_store.store_report import get_patient_by_id, check_duplicate_report, store_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_report(
    patient_id: int = Form(..., description="ID of the patient"),
    file: UploadFile = File(..., description="PDF file of medical report"),
    strategy: str = Form("auto", description="Extraction strategy: 'auto' (default), 'text', or 'vision'"),
    db: Session = Depends(get_db)
):
    """
    Upload a medical report PDF and process it into structured database records.

    Workflow:
      1. Upload PDF to Cloudinary
      2. Extract structured data using LLM (auto-detects text vs scanned)
      3. Lookup patient, check duplicate
      4. Store Report + ReportDescription rows

    Strategy:
      - 'auto' (default): Automatically detect if PDF is text-based or scanned
      - 'text': Force text-based extraction
      - 'vision': Force vision-based extraction for scanned PDFs
    """

    # ── Validate file type ────────────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted"
        )

    cloudinary_public_id: Optional[str] = None

    try:
        # ── STEP 1: Read PDF into memory ──────────────────────────────────────
        # Read the entire file into memory
        pdf_content = await file.read()
        file.file.seek(0)  # Reset file pointer for Cloudinary upload
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{Path(file.filename).name}"
        
        logger.info(f"Read PDF into memory: {safe_filename} ({len(pdf_content)} bytes)")

        # ── STEP 2: Upload to Cloudinary ──────────────────────────────────────
        from services.storage.cloudinary_storage import upload_medical_pdf
        from io import BytesIO
        
        try:
            # Create BytesIO from content for Cloudinary
            pdf_buffer = BytesIO(pdf_content)
            cloudinary_result = upload_medical_pdf(
                file=pdf_buffer,
                filename=safe_filename,
                document_type="report",
                patient_id=patient_id
            )
            
            cloudinary_url = cloudinary_result["secure_url"]
            cloudinary_public_id = cloudinary_result["public_id"]
            
            logger.info(f"Uploaded to Cloudinary: {cloudinary_public_id}")
        except Exception as cloud_err:
            logger.error(f"Cloudinary upload failed: {cloud_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload PDF to cloud storage: {str(cloud_err)}"
            )

        # ── STEP 3: Extract structured data with LLM ──────────────────────────
        try:
            # Create another BytesIO for extraction
            from services.parsers.report_parser import parse_pdf_from_memory
            pdf_buffer = BytesIO(pdf_content)
            validated_report = parse_pdf_from_memory(pdf_buffer, safe_filename, strategy=strategy)
            logger.info(
                f"LLM extracted: {validated_report.header.report_name}, "
                f"{len(validated_report.test_results)} tests"
            )
        except Exception as parse_err:
            logger.error(f"PDF parsing failed: {parse_err}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not extract data from PDF: {str(parse_err)[:300]}"
            )

        # ── STEP 4: Validate required fields ──────────────────────────────────
        if not validated_report.header.report_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract report name from PDF."
            )

        if not validated_report.test_results:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No test results found in PDF."
            )

        # ── STEP 5: Lookup patient ────────────────────────────────────────────
        patient = get_patient_by_id(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient with ID {patient_id} not found."
            )

        # ── STEP 6: Duplicate check ───────────────────────────────────────────
        from services.db_store.store_report import parse_date
        report_date = parse_date(validated_report.header.report_date)
        
        is_duplicate = check_duplicate_report(
            db,
            patient.id,
            validated_report.header.report_name,
            report_date,
        )
        if is_duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Report '{validated_report.header.report_name}' for patient {patient_id} "
                    f"dated {validated_report.header.report_date} already exists."
                )
            )

        # ── STEP 7: Store in database with Cloudinary URL ─────────────────────
        report = store_report(
            db=db,
            validated_report=validated_report,
            patient_id=patient.id,
            report_url=cloudinary_url,
        )

        return {
            "success": True,
            "message": "Report processed and stored successfully",
            "data": {
                "report_id": report.id,
                "report_name": report.report_name,
                "patient_id": report.patient_id,
                "patient_email": patient.email,
                "report_date": report.report_date.isoformat() if report.report_date else None,
                "collection_date": report.collection_date.isoformat() if report.collection_date else None,
                "received_date": report.received_date.isoformat() if report.received_date else None,
                "specimen_type": report.specimen_type,
                "status": report.status,
                "test_results_count": len(validated_report.test_results),
                "cloudinary_url": cloudinary_url,
                "cloudinary_public_id": cloudinary_public_id,
            },
            "processing": {
                "extraction_strategy": strategy,
                "file_size_bytes": len(pdf_content),
            }
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error processing report")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(exc)}"
        )
    finally:
        file.file.close()
        # No temporary file cleanup needed - everything was in memory!


@router.get("/test-services")
async def test_services():
    """Check if all report processing services are importable and configured."""
    from core.config import settings

    results: dict = {"services": {}, "configuration": {}}

    for name, import_fn in [
        ("report_parser", lambda: __import__(
            "services.parsers.report_parser", fromlist=["parse_pdf"]
        )),
        ("llm_report_validator", lambda: __import__(
            "services.llm_validators.llm_report_validator", fromlist=["extract_structured_report"]
        )),
        ("store_report", lambda: __import__(
            "services.db_store.store_report", fromlist=["store_report"]
        )),
    ]:
        try:
            import_fn()
            results["services"][name] = {"status": "OK"}
        except Exception as e:
            results["services"][name] = {"status": "ERROR", "error": str(e)}

    results["configuration"] = {
        "groq_api_key_set": bool(getattr(settings, "GROQ_API_KEY", None)),
        "langsmith_tracing": getattr(settings, "LANGSMITH_TRACING", False),
        "langsmith_project": getattr(settings, "LANGSMITH_PROJECT", None),
    }

    all_ok = all(s.get("status") == "OK" for s in results["services"].values())
    results["overall_status"] = "OK" if all_ok else "DEGRADED"

    return results