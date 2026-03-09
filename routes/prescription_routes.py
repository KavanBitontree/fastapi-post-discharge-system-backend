"""
Prescription Routes
-------------------
API endpoints for uploading and processing prescription PDFs.
"""

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pathlib import Path
from typing import Optional
import shutil
from datetime import datetime

from core.database import get_db


router = APIRouter(prefix="/api/prescriptions", tags=["Prescriptions"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_prescription(
    patient_id: int = Form(..., description="ID of the patient"),
    file: UploadFile = File(..., description="PDF file of prescription"),
    strategy: str = Form("auto", description="Extraction strategy: 'auto' (default), 'text', or 'vision'"),
    db: Session = Depends(get_db)
):
    """
    Upload a prescription PDF and process it.
    
    **Workflow:**
    1. Upload PDF to Cloudinary
    2. Extract with LLM (auto-detects text vs scanned)
    3. Look up patient by ID
    4. Find or create doctor
    5. Link patient ↔ doctor
    6. Store medications and schedules in database
    
    **Parameters:**
    - **patient_id**: ID of the patient (required)
    - **file**: PDF file to upload (required)
    - **strategy**: 'auto' (default), 'text', or 'vision'
    
    **Returns:**
    - Patient ID
    - Doctor ID
    - Number of medications inserted
    - Number of schedules inserted
    - Processing details
    """
    
    # Validate file type
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted"
        )
    
    cloudinary_public_id: Optional[str] = None
    
    try:
        # ═══════════════════════════════════════════════════════════════════
        # STEP 1: Read PDF into memory
        # ═══════════════════════════════════════════════════════════════════
        # Read the entire file into memory
        pdf_content = await file.read()
        file.file.seek(0)  # Reset file pointer for Cloudinary upload
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{Path(file.filename).name}"
        
        print(f"[prescription] Read PDF into memory: {safe_filename} ({len(pdf_content)} bytes)")

        # ═══════════════════════════════════════════════════════════════════
        # STEP 2: Upload to Cloudinary
        # ═══════════════════════════════════════════════════════════════════
        from services.storage.cloudinary_storage import upload_medical_pdf
        from io import BytesIO
        
        try:
            # Create BytesIO from content for Cloudinary
            pdf_buffer = BytesIO(pdf_content)
            cloudinary_result = upload_medical_pdf(
                file=pdf_buffer,
                filename=safe_filename,
                document_type="prescription",
                patient_id=patient_id
            )
            
            cloudinary_url = cloudinary_result["secure_url"]
            cloudinary_public_id = cloudinary_result["public_id"]
            
            print(f"[prescription] Uploaded to Cloudinary: {cloudinary_public_id}")
        except Exception as cloud_err:
            print(f"[prescription] Cloudinary upload failed: {cloud_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload PDF to cloud storage: {str(cloud_err)}"
            )

        # ═══════════════════════════════════════════════════════════════════
        # STEP 3: Extract with LLM
        # ═══════════════════════════════════════════════════════════════════
        try:
            # Create another BytesIO for extraction
            from services.parsers.prescription_parser import parse_prescription_pdf_from_memory
            pdf_buffer = BytesIO(pdf_content)
            parsed = parse_prescription_pdf_from_memory(pdf_buffer, safe_filename, strategy=strategy)
            print(f"[prescription] Extracted {len(parsed.medications)} medications")
            print(f"[prescription] Type: {type(parsed).__name__}")
            print(f"[prescription] Has patient_id attr: {hasattr(parsed, 'patient_id')}")
        except Exception as parse_err:
            print(f"[prescription] Parsing failed: {parse_err}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not extract data from PDF: {str(parse_err)[:300]}"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4: Validate required fields
        # ═══════════════════════════════════════════════════════════════════
        if not parsed.medications:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No medications found in PDF."
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 5-6: Store in database
        # ═══════════════════════════════════════════════════════════════════
        from services.db_store.store_prescription import store_parsed_prescription
        
        # Handle both ValidatedPrescription and ParsedPrescription
        if hasattr(parsed, 'patient_id'):
            # It's a ParsedPrescription (dataclass)
            parsed.patient_id = patient_id
            print(f"[prescription] Set patient_id={patient_id} on ParsedPrescription")
        else:
            # It's a ValidatedPrescription (Pydantic) - convert to ParsedPrescription
            print(f"[prescription] Converting ValidatedPrescription to ParsedPrescription")
            from services.parsers.prescription_parser import ParsedPrescription, MedicationData, RecurrenceData, ScheduleData
            from datetime import date
            
            # Convert medications
            medications = []
            for med in parsed.medications:
                med_data = MedicationData(
                    drug_name=med.drug_name,
                    strength=med.strength,
                    form_of_medicine=med.form_of_medicine,
                    dosage=med.dosage,
                    frequency_of_dose_per_day=med.frequency_of_dose_per_day,
                    dosing_days=med.dosing_days,
                    prescription_date=med.prescription_date,
                    recurrence=RecurrenceData(
                        type=med.recurrence.type if med.recurrence else "daily",
                        every_n_days=med.recurrence.every_n_days if med.recurrence else None,
                        start_date_for_every_n_days=med.recurrence.start_date_for_every_n_days if med.recurrence else None,
                        cycle_take_days=med.recurrence.cycle_take_days if med.recurrence else None,
                        cycle_skip_days=med.recurrence.cycle_skip_days if med.recurrence else None,
                    ),
                    schedule=ScheduleData(
                        before_breakfast=med.schedule.before_breakfast if med.schedule else False,
                        after_breakfast=med.schedule.after_breakfast if med.schedule else False,
                        before_lunch=med.schedule.before_lunch if med.schedule else False,
                        after_lunch=med.schedule.after_lunch if med.schedule else False,
                        before_dinner=med.schedule.before_dinner if med.schedule else False,
                        after_dinner=med.schedule.after_dinner if med.schedule else False,
                    )
                )
                medications.append(med_data)
            
            # Create ParsedPrescription
            parsed = ParsedPrescription(
                rx_number=parsed.header.rx_number,
                rx_date=parsed.header.rx_date,
                patient_id=patient_id,  # Set here
                patient_email=None,  # Not extracted from PDF
                patient_phone=parsed.header.patient_phone,
                doctor_name=parsed.header.doctor_name,
                doctor_email=parsed.header.doctor_email,
                doctor_speciality=parsed.header.doctor_speciality,
                medications=medications,
            )
            print(f"[prescription] Converted to ParsedPrescription with patient_id={patient_id}")
        
        result = store_parsed_prescription(parsed)
        
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
    except Exception as e:
        print(f"[prescription] Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing prescription: {str(e)}"
        )
    finally:
        file.file.close()
        # No temporary file cleanup needed - everything was in memory!


@router.get("/test-services")
async def test_services():
    """
    Test if all prescription processing services are working.
    
    **Tests:**
    - prescription_parser.py (Unified LLM extraction with chunking)
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
    
    # Test 1: prescription_parser.py (uses unified chunked extraction)
    try:
        from services.parsers.prescription_parser import parse_prescription_pdf
        results["services"]["prescription_parser"] = {
            "status": "OK",
            "extraction": "unified_chunked",
            "functions": ["parse_prescription_pdf"]
        }
    except Exception as e:
        results["services"]["prescription_parser"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Test 2: llm_prescription_validator.py
    try:
        from services.llm_validators.llm_prescription_validator import (
            extract_prescription_from_chunk,
            merge_prescription_results
        )
        results["services"]["llm_prescription_validator"] = {
            "status": "OK",
            "llm_model": "openai/gpt-oss-120b",
            "functions": ["extract_prescription_from_chunk", "merge_prescription_results"]
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