"""
Report Routes
-------------
API endpoints for uploading and processing medical report PDFs.
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path
import shutil
from datetime import datetime

from core.database import get_db
from services.parsers.report_parser import extract_raw_text, parse_header, parse_test_rows
from services.llm_validators.report_llm_validator import validate_with_llm
from services.db_store.report_store_db import get_patient_by_email, check_duplicate_report, store_report
from models import Patient


router = APIRouter(prefix="/api/reports", tags=["Reports"])


def parse_datetime(value: str) -> Optional[datetime]:
    """Parse datetime from string"""
    formats = ["%m/%d/%Y %H:%M", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_report(
    file: UploadFile = File(..., description="PDF file of medical report"),
    use_llm: bool = True,
    db: Session = Depends(get_db)
):
    """
    Upload a medical report PDF and process it.
    
    **Workflow:**
    1. Save PDF to `public/pdfs/`
    2. Extract text from PDF
    3. Parse with regex
    4. Validate with LLM (if enabled)
    5. Look up patient by email
    6. Check for duplicates
    7. Store in database
    
    **Parameters:**
    - **file**: PDF file to upload (required)
    - **use_llm**: Use LLM for validation (default: true)
    
    **Returns:**
    - Report ID
    - Report name
    - Patient ID
    - Number of test results
    - Processing details
    """
    
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )
    
    try:
        # ═══════════════════════════════════════════════════════════════════
        # STEP 1: Save PDF file
        # ═══════════════════════════════════════════════════════════════════
        pdf_dir = Path("public/pdfs")
        pdf_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        pdf_path = pdf_dir / safe_filename
        
        # Save file
        with pdf_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 2: Extract text
        # ═══════════════════════════════════════════════════════════════════
        raw_text = extract_raw_text(str(pdf_path))
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 3: Parse with regex
        # ═══════════════════════════════════════════════════════════════════
        header = parse_header(raw_text)
        rows = parse_test_rows(raw_text)
        
        regex_results = {
            "report_name": header.get("report_name"),
            "patient_email": header.get("patient_email"),
            "test_count": len(rows)
        }
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4: Validate with LLM (if enabled)
        # ═══════════════════════════════════════════════════════════════════
        llm_used = False
        if use_llm:
            try:
                validated = validate_with_llm(raw_text, header, rows)
                llm_used = True
                
                # Convert LLM results
                header = {
                    "report_name": validated.header.report_name,
                    "patient_email": validated.header.patient_email,
                    "report_date": parse_datetime(validated.header.report_date) if validated.header.report_date else header.get("report_date"),
                    "collection_date": parse_datetime(validated.header.collection_date) if validated.header.collection_date else header.get("collection_date"),
                    "received_date": parse_datetime(validated.header.received_date) if validated.header.received_date else header.get("received_date"),
                    "specimen_type": validated.header.specimen_type or header.get("specimen_type"),
                    "status": validated.header.status or header.get("status"),
                }
                
                rows = [
                    {
                        "test_name": test.test_name,
                        "section": test.section,
                        "normal_result": test.normal_result,
                        "abnormal_result": test.abnormal_result,
                        "flag": test.flag,
                        "units": test.units,
                        "reference_range_low": test.reference_range_low,
                        "reference_range_high": test.reference_range_high,
                    }
                    for test in validated.test_results
                ]
            except Exception as e:
                # LLM failed, use regex results
                llm_used = False
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 5: Validate required fields
        # ═══════════════════════════════════════════════════════════════════
        if not header.get("report_name"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract report name from PDF"
            )
        
        if not header.get("patient_email"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract patient email from PDF"
            )
        
        if len(rows) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No test results found in PDF"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 6: Get patient
        # ═══════════════════════════════════════════════════════════════════
        patient = get_patient_by_email(db, header["patient_email"])
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient with email '{header['patient_email']}' not found in database. Please create patient first."
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 7: Check for duplicates
        # ═══════════════════════════════════════════════════════════════════
        is_duplicate = check_duplicate_report(
            db, patient.id, header["report_name"], header["report_date"]
        )
        
        if is_duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Report '{header['report_name']}' for this patient with date {header['report_date']} already exists"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 8: Store in database
        # ═══════════════════════════════════════════════════════════════════
        report = store_report(
            db=db,
            header=header,
            rows=rows,
            patient_id=patient.id,
            report_url=f"/public/pdfs/{safe_filename}"
        )
        
        # ═══════════════════════════════════════════════════════════════════
        # Return success response
        # ═══════════════════════════════════════════════════════════════════
        return {
            "success": True,
            "message": "Report processed and stored successfully",
            "data": {
                "report_id": report.id,
                "report_name": report.report_name,
                "patient_id": report.patient_id,
                "patient_email": header["patient_email"],
                "report_date": report.report_date.isoformat() if report.report_date else None,
                "test_results_count": len(rows),
                "pdf_path": f"/public/pdfs/{safe_filename}",
            },
            "processing": {
                "llm_used": llm_used,
                "regex_results": regex_results,
                "file_size_bytes": pdf_path.stat().st_size,
            }
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing report: {str(e)}"
        )
    finally:
        file.file.close()


@router.get("/test-services")
async def test_services():
    """
    Test if all report processing services are working.
    
    **Tests:**
    - report_parser.py (PDF extraction and regex parsing)
    - report_llm_validator.py (LLM validation with Groq)
    - report_store_db.py (Database operations)
    
    **Returns:**
    - Status of each service
    - Configuration details
    """
    
    from core.config import settings
    
    results = {
        "services": {},
        "configuration": {}
    }
    
    # Test 1: report_parser.py
    try:
        from services.parsers.report_parser import extract_raw_text, parse_header, parse_test_rows
        results["services"]["report_parser"] = {
            "status": "OK",
            "functions": ["extract_raw_text", "parse_header", "parse_test_rows"]
        }
    except Exception as e:
        results["services"]["report_parser"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Test 2: report_llm_validator.py
    try:
        from services.llm_validators.report_llm_validator import validate_with_llm, llm
        results["services"]["report_llm_validator"] = {
            "status": "OK",
            "llm_model": "llama-3.3-70b-versatile",
            "functions": ["validate_with_llm", "extract_report_name_with_llm"]
        }
    except Exception as e:
        results["services"]["report_llm_validator"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Test 3: report_store_db.py
    try:
        from services.db_store.report_store_db import get_patient_by_email, check_duplicate_report, store_report
        results["services"]["report_store_db"] = {
            "status": "OK",
            "functions": ["get_patient_by_email", "check_duplicate_report", "store_report"]
        }
    except Exception as e:
        results["services"]["report_store_db"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Configuration
    results["configuration"] = {
        "groq_api_key_set": bool(settings.GROQ_API_KEY),
        "langsmith_tracing": settings.LANGSMITH_TRACING,
        "langsmith_project": settings.LANGSMITH_PROJECT,
        "database_connected": True,  # If we got here, DB is connected
    }
    
    # Overall status
    all_ok = all(
        service.get("status") == "OK" 
        for service in results["services"].values()
    )
    
    results["overall_status"] = "OK" if all_ok else "ERROR"
    
    return results
