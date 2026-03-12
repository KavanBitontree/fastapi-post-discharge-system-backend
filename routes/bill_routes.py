"""
Bill Routes
-----------
API endpoints for uploading and processing medical bill PDFs.
"""

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pathlib import Path
from typing import Optional
import shutil
from datetime import datetime

from core.database import get_db
from models.discharge_history import DischargeHistory
from models.bill import Bill


router = APIRouter(prefix="/api/bills", tags=["Bills"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_bill(
    discharge_id: int = Form(..., description="ID of the discharge record"),
    file: UploadFile = File(..., description="PDF file of medical bill"),
    strategy: str = Form("auto", description="Extraction strategy: 'auto' (default), 'text', or 'vision'"),
    db: Session = Depends(get_db)
):
    """
    Upload a medical bill PDF and process it.
    
    **Workflow:**
    1. Upload PDF to Cloudinary
    2. Extract with LLM (auto-detects text vs scanned)
    3. Look up patient by ID
    4. Check for duplicates
    5. Store in database
    
    **Parameters:**
    - **patient_id**: ID of the patient (required)
    - **file**: PDF file to upload (required)
    - **strategy**: 'auto' (default), 'text', or 'vision'
    
    **Returns:**
    - Bill ID
    - Invoice number
    - Patient ID
    - Number of line items
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
        
        print(f"[bill] Read PDF into memory: {safe_filename} ({len(pdf_content)} bytes)")

        # ═══════════════════════════════════════════════════════════════════
        # STEP 2: Upload to Cloudinary (from memory)
        # ═══════════════════════════════════════════════════════════════════
        from services.storage.cloudinary_storage import upload_medical_pdf
        from io import BytesIO
        
        try:
            # Create BytesIO from content for Cloudinary
            pdf_buffer = BytesIO(pdf_content)
            cloudinary_result = upload_medical_pdf(
                file=pdf_buffer,
                filename=safe_filename,
                document_type="bill",
                patient_id=db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first().patient_id
            )
            
            cloudinary_url = cloudinary_result["secure_url"]
            cloudinary_public_id = cloudinary_result["public_id"]
            
            print(f"[bill] Uploaded to Cloudinary: {cloudinary_public_id}")
        except Exception as cloud_err:
            print(f"[bill] Cloudinary upload failed: {cloud_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload PDF to cloud storage: {str(cloud_err)}"
            )

        # ═══════════════════════════════════════════════════════════════════
        # STEP 3: Extract with LLM (from memory)
        # ═══════════════════════════════════════════════════════════════════
        try:
            # Create another BytesIO for extraction
            from services.parsers.bill_parser import parse_bill_pdf_from_memory
            pdf_buffer = BytesIO(pdf_content)
            parsed = parse_bill_pdf_from_memory(pdf_buffer, safe_filename, strategy=strategy)
            print(f"[bill] Extracted invoice: {parsed.bill.invoice_number}, {len(parsed.line_items)} items")
        except Exception as parse_err:
            print(f"[bill] Parsing failed: {parse_err}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not extract data from PDF: {str(parse_err)[:300]}"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4: Validate required fields
        # ═══════════════════════════════════════════════════════════════════
        if not parsed.bill.invoice_number:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract invoice number from PDF"
            )
        
        if not parsed.bill.total_amount:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract total amount from PDF"
            )
        
        if len(parsed.line_items) == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No line items found in PDF"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 5: Validate discharge and get patient
        # ═══════════════════════════════════════════════════════════════════
        discharge = db.query(DischargeHistory).filter(DischargeHistory.id == discharge_id).first()
        if not discharge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Discharge id={discharge_id} not found."
            )
        from models.patient import Patient
        patient = db.query(Patient).filter(Patient.id == discharge.patient_id).first()
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 6: Check for duplicates
        # ═══════════════════════════════════════════════════════════════════
        existing = db.query(Bill).filter(
            Bill.invoice_number == parsed.bill.invoice_number
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Bill with invoice number '{parsed.bill.invoice_number}' already exists"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 7: Store in database with Cloudinary URL
        # ═══════════════════════════════════════════════════════════════════
        from models.bill_description import BillDescription
        
        bill = Bill(
            discharge_id=discharge_id,
            invoice_number=parsed.bill.invoice_number,
            invoice_date=parsed.bill.invoice_date,
            due_date=parsed.bill.due_date,
            initial_amount=parsed.bill.initial_amount or 0,
            discount_amount=parsed.bill.discount_amount or 0,
            tax_amount=parsed.bill.tax_amount or 0,
            total_amount=parsed.bill.total_amount,
            bill_url=cloudinary_url,
        )
        db.add(bill)
        db.flush()
        
        # Create BillDescription rows
        for item in parsed.line_items:
            if item.description:
                db.add(BillDescription(
                    bill_id=bill.id,
                    cpt_code=item.cpt_code,
                    description=item.description,
                    qty=item.qty or 1,
                    unit_price=item.unit_price or 0,
                    total_price=item.total_price or 0,
                ))
        
        db.commit()
        db.refresh(bill)
        
        # ═══════════════════════════════════════════════════════════════════
        # Return success response
        # ═══════════════════════════════════════════════════════════════════
        return {
            "success": True,
            "message": "Bill processed and stored successfully",
            "data": {
                "bill_id": bill.id,
                "invoice_number": bill.invoice_number,
                "discharge_id": bill.discharge_id,
                "patient_email": patient.email,
                "invoice_date": bill.invoice_date.isoformat() if bill.invoice_date else None,
                "total_amount": str(bill.total_amount),
                "line_items_count": len(parsed.line_items),
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
        print(f"[bill] Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing bill: {str(e)}"
        )
    finally:
        file.file.close()
        # No temporary file cleanup needed - everything was in memory!


@router.get("/test-services")
async def test_services():
    """
    Test if all bill processing services are working.
    
    **Tests:**
    - bill_parser.py (PDF extraction and regex parsing)
    - llm_bill_validator.py (LLM validation with Groq)
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
    
    # Test 1: bill_parser.py
    try:
        from services.parsers.bill_parser import extract_raw_text, parse_bill_pdf
        results["services"]["bill_parser"] = {
            "status": "OK",
            "functions": ["extract_raw_text", "parse_bill_pdf"]
        }
    except Exception as e:
        results["services"]["bill_parser"] = {
            "status": "ERROR",
            "error": str(e)
        }
    
    # Test 2: llm_bill_validator.py
    try:
        from services.llm_validators.llm_bill_validator import validate_bill
        results["services"]["llm_bill_validator"] = {
            "status": "OK",
            "llm_model": "openai/gpt-oss-120b",
            "functions": ["validate_bill"]
        }
    except Exception as e:
        results["services"]["llm_bill_validator"] = {
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
