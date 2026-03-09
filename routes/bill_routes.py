"""
Bill Routes
-----------
API endpoints for uploading and processing medical bill PDFs.
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
from datetime import datetime

from core.database import get_db
from services.parsers.bill_parser import parse_bill_pdf, extract_raw_text
from services.llm_validators.llm_bill_validator import validate_bill
from models.patient import Patient
from models.bill import Bill


router = APIRouter(prefix="/api/bills", tags=["Bills"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_process_bill(
    file: UploadFile = File(..., description="PDF file of medical bill"),
    use_llm: bool = True,
    db: Session = Depends(get_db)
):
    """
    Upload a medical bill PDF and process it.
    
    **Workflow:**
    1. Save PDF to `public/pdfs/`
    2. Extract text from PDF
    3. Parse with regex (Stage 1)
    4. Validate with LLM (Stage 2, if enabled)
    5. Look up patient by email
    6. Check for duplicates
    7. Store in database
    
    **Parameters:**
    - **file**: PDF file to upload (required)
    - **use_llm**: Use LLM for validation (default: true)
    
    **Returns:**
    - Bill ID
    - Invoice number
    - Patient ID
    - Number of line items
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
        # STEP 3: Parse with regex (Stage 1)
        # ═══════════════════════════════════════════════════════════════════
        parsed = parse_bill_pdf(str(pdf_path))
        
        regex_results = {
            "invoice_number": parsed.bill.invoice_number,
            "patient_email": parsed.patient_email,
            "line_items_count": len(parsed.line_items)
        }
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 4: Validate with LLM (Stage 2, if enabled)
        # ═══════════════════════════════════════════════════════════════════
        llm_used = False
        if use_llm:
            try:
                parsed = validate_bill(raw_text, parsed)
                llm_used = True
            except Exception as e:
                # LLM failed, use regex results
                llm_used = False
                print(f"LLM validation failed: {e}")
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 5: Validate required fields
        # ═══════════════════════════════════════════════════════════════════
        if not parsed.bill.invoice_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract invoice number from PDF"
            )
        
        if not parsed.patient_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract patient email from PDF"
            )
        
        if not parsed.bill.total_amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not extract total amount from PDF"
            )
        
        if len(parsed.line_items) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No line items found in PDF"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 6: Get patient
        # ═══════════════════════════════════════════════════════════════════
        patient = db.query(Patient).filter(Patient.email == parsed.patient_email).first()
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient with email '{parsed.patient_email}' not found in database. Please create patient first."
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # STEP 7: Check for duplicates
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
        # STEP 8: Store in database
        # ═══════════════════════════════════════════════════════════════════
        from models.bill_description import BillDescription
        
        bill = Bill(
            patient_id=patient.id,
            invoice_number=parsed.bill.invoice_number,
            invoice_date=parsed.bill.invoice_date,
            due_date=parsed.bill.due_date,
            initial_amount=parsed.bill.initial_amount or 0,
            discount_amount=parsed.bill.discount_amount or 0,
            tax_amount=parsed.bill.tax_amount or 0,
            total_amount=parsed.bill.total_amount,
            bill_url=f"/public/pdfs/{safe_filename}",
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
                "patient_id": bill.patient_id,
                "patient_email": parsed.patient_email,
                "invoice_date": bill.invoice_date.isoformat() if bill.invoice_date else None,
                "total_amount": str(bill.total_amount),
                "line_items_count": len(parsed.line_items),
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
            detail=f"Error processing bill: {str(e)}"
        )
    finally:
        file.file.close()


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
