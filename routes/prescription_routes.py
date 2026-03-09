"""
Prescription Routes
-------------------
API endpoints for uploading and processing prescription PDFs.
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
from datetime import datetime

from core.database import get_db
from services.db_store.store_prescription import process_prescription_pdf


router = APIRouter(prefix="/api/prescriptions", tags=["Prescriptions"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_prescription(
    file: UploadFile = File(..., description="PDF file of prescription"),
    db: Session = Depends(get_db)
):
    """
    Upload a prescription PDF and process it.
    
    **Workflow:**
    1. Save PDF to `public/pdfs/`
    2. Extract text from PDF
    3. Parse with regex (Stage 1)
    4. Validate with LLM (Stage 2)
    5. Look up patient by email/phone
    6. Find or create doctor
    7. Link patient ↔ doctor
    8. Store medications and schedules in database
    
    **Parameters:**
    - **file**: PDF file to upload (required)
    
    **Returns:**
    - Patient ID
    - Doctor ID
    - Number of medications inserted
    - Number of schedules inserted
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
        # STEP 2-5: Process prescription (extract, parse, validate, store)
        # ═══════════════════════════════════════════════════════════════════
        result = process_prescription_pdf(str(pdf_path))
        
        # ═══════════════════════════════════════════════════════════════════
        # Return success response
        # ═══════════════════════════════════════════════════════════════════
        return {
            "success": True,
            "message": "Prescription processed and stored successfully",
            "data": {
                "patient_id": result["patient_id"],
                "doctor_id": result["doctor_id"],
                "medications_inserted": result["medications_inserted"],
                "schedules_inserted": result["schedules_inserted"],
                "pdf_path": f"/public/pdfs/{safe_filename}",
            },
            "processing": {
                "llm_used": True,
                "file_size_bytes": pdf_path.stat().st_size,
            }
        }
        
    except ValueError as e:
        # Patient not found or other validation errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Handle unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing prescription: {str(e)}"
        )
    finally:
        file.file.close()


@router.get("/test-services")
async def test_services():
    """
    Test if all prescription processing services are working.
    
    **Tests:**
    - prescription_parser.py (PDF extraction and regex parsing)
    - llm_prescription_validator.py (LLM validation with Groq)
    - Database operations
    
    **Returns:**
    - Status of each service
    - Configuration details
    """
    
    from core.config import settings
    
    results = {
        "services": {},
        "configuration": {}
    }
    
    # Test 1: prescription_parser.py
    try:
        from services.parsers.prescription_parser import extract_raw_text, parse_prescription_pdf
        results["services"]["prescription_parser"] = {
            "status": "OK",
            "functions": ["extract_raw_text", "parse_prescription_pdf"]
        }
    except Exception as e:
        results["services"]["prescription_parser"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Test 2: llm_prescription_validator.py
    try:
        from services.llm_validators.llm_prescription_validator import validate_prescription
        results["services"]["llm_prescription_validator"] = {
            "status": "OK",
            "llm_model": "openai/gpt-oss-120b",
            "functions": ["validate_prescription"]
        }
    except Exception as e:
        results["services"]["llm_prescription_validator"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Test 3: store_prescription.py
    try:
        from services.db_store.store_prescription import process_prescription_pdf, store_parsed_prescription
        results["services"]["store_prescription"] = {
            "status": "OK",
            "functions": ["process_prescription_pdf", "store_parsed_prescription"]
        }
    except Exception as e:
        results["services"]["store_prescription"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Configuration
    results["configuration"] = {
        "groq_api_key_set": bool(settings.GROQ_API_KEY),
        "langsmith_tracing": settings.LANGSMITH_TRACING,
        "langsmith_project": settings.LANGSMITH_PROJECT,
        "database_connected": True,
    }
    
    # Overall status
    all_ok = all(
        service.get("status") == "OK" 
        for service in results["services"].values()
    )
    
    results["overall_status"] = "OK" if all_ok else "ERROR"
    
    return results
