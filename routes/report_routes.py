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
from core.security import get_current_user
from services.parsers.report_parser import parse_pdf
from services.db_store.store_report import get_patient_by_id, check_duplicate_report, store_report
from models.discharge_history import DischargeHistory
from models.report import Report
from models.report_description import ReportDescription
from schemas.report_schemas import ReportSummaryResponse, ReportSummaryItem, TestResultItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_report(
    discharge_id: int = Form(..., description="ID of the discharge record"),
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

        # Resolve patient_id via discharge for Cloudinary folder organisation
        discharge = db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first()
        if not discharge:
            raise HTTPException(status_code=404, detail=f"Discharge id={discharge_id} not found.")
        patient_id = discharge.patient_id
        
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

        # ── STEP 5: Lookup patient via discharge ─────────────────────────────
        discharge = db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first()
        if not discharge:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Discharge id={discharge_id} not found.")
        patient = get_patient_by_id(db, discharge.patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient for discharge id={discharge_id} not found."
            )

        # ── STEP 6: Duplicate check ───────────────────────────────────────────
        from services.db_store.store_report import parse_date
        report_date = parse_date(validated_report.header.report_date)
        
        is_duplicate = check_duplicate_report(
            db,
            discharge_id,
            validated_report.header.report_name,
            report_date,
        )
        if is_duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Report '{validated_report.header.report_name}' for discharge {discharge_id} "
                    f"dated {validated_report.header.report_date} already exists."
                )
            )

        # ── STEP 7: Store in database with Cloudinary URL ─────────────────────
        report = store_report(
            db=db,
            validated_report=validated_report,
            discharge_id=discharge_id,
            report_url=cloudinary_url,
        )

        return {
            "success": True,
            "message": "Report processed and stored successfully",
            "data": {
                "report_id": report.id,
                "report_name": report.report_name,
                "discharge_id": report.discharge_id,
                "patient_id": patient.id,  # Use patient_id instead of email
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



@router.get("/discharge/{discharge_id}/summary", response_model=ReportSummaryResponse)
async def get_discharge_report_summary(
    discharge_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a structured summary of all reports for a given discharge ID.
    
    Returns all reports with their test results, including computed flags
    based on reference ranges when the flag column is not populated.
    
    Flag logic:
    - If flag column has a value → use it directly ("H", "L", "**")
    - Else if reference ranges exist → compute flag by comparing result value
    - Else → no flag
    """
    
    # Verify discharge exists
    discharge = db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first()
    if not discharge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discharge with id {discharge_id} not found"
        )
    
    # Query all reports for this discharge
    reports = db.query(Report).filter(Report.discharge_id == discharge_id).all()
    
    report_summaries = []
    
    for report in reports:
        # Query all test descriptions for this report
        descriptions = db.query(ReportDescription).filter(
            ReportDescription.report_id == report.id
        ).all()
        
        test_items = []
        
        for desc in descriptions:
            # Helper function to get result value with proper priority
            def get_result_value(desc):
                # Priority 1: abnormal_result (flagged/out-of-range value)
                if desc.abnormal_result is not None and str(desc.abnormal_result).strip() != "":
                    return str(desc.abnormal_result).strip()
                # Priority 2: normal_result (within-range value)
                if desc.normal_result is not None and str(desc.normal_result).strip() != "":
                    return str(desc.normal_result).strip()
                return None
            
            # Determine the result value to display
            result_value = get_result_value(desc)
            
            # Determine flag and flag_source
            flag = None
            flag_source = None
            
            # Priority 1: Use flag column if present
            if desc.flag is not None and desc.flag.strip() != "":
                flag = desc.flag.strip()
                flag_source = "column"
            # Priority 2: Compute from reference ranges
            elif desc.reference_range_low and desc.reference_range_high and result_value:
                try:
                    # Try to parse the result value as a float
                    actual_value = float(result_value)
                    range_low = float(desc.reference_range_low)
                    range_high = float(desc.reference_range_high)
                    
                    if actual_value > range_high:
                        flag = "H"
                        flag_source = "computed"
                    elif actual_value < range_low:
                        flag = "L"
                        flag_source = "computed"
                except (ValueError, TypeError):
                    # If parsing fails, leave flag as None
                    pass
            
            test_items.append(TestResultItem(
                test_name=desc.test_name,
                section=desc.section,
                result=result_value,
                units=desc.units,
                flag=flag,
                flag_source=flag_source,
                reference_range_low=desc.reference_range_low,
                reference_range_high=desc.reference_range_high
            ))
        
        report_summaries.append(ReportSummaryItem(
            report_id=report.id,
            report_name=report.report_name,
            report_date=report.report_date.isoformat() if report.report_date else None,
            specimen_type=report.specimen_type,
            tests=test_items
        ))
    
    return ReportSummaryResponse(
        discharge_id=discharge_id,
        reports=report_summaries
    )
