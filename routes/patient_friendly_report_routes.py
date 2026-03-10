"""
patient_friendly_report_routes.py
----------------------------------
API endpoint for converting discharge summary PDFs to patient-friendly reports.
"""

from fastapi import APIRouter, Depends, status, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.patient_friendly_report_schemas import (
    PatientFriendlyReportRequest,
    PatientFriendlyReportResponse
)
from controllers.patient_friendly_report_controller import PatientFriendlyReportController
from services.pdf_generator import generate_patient_friendly_pdf
import pdfplumber
from io import BytesIO
import time


router = APIRouter(
    prefix="/api/patient-friendly-report",
    tags=["Patient Friendly Reports"]
)


@router.post(
    "/convert-pdf",
    status_code=status.HTTP_200_OK
)
async def convert_discharge_summary_pdf(
    file: UploadFile = File(..., description="PDF file of discharge summary (15-16 pages)"),
    db: Session = Depends(get_db)
):
    """
    Upload a discharge summary PDF and get a patient-friendly PDF report.
    
    This is the MAIN endpoint - just upload your PDF and get the simplified report in PDF format!
    
    Process:
    1. Upload PDF file (any size, 1-20 pages)
    2. Extract text from PDF
    3. Convert medical jargon to simple language
    4. Generate attractive PDF report
    5. Return formatted PDF for download
    
    Returns:
    - Patient-friendly PDF report (1 page, easy to read)
    - Summary (500-700 words in simple language)
    - Key points (3-5 bullet points)
    - Medications in simple terms
    - Follow-up instructions
    - Warning signs highlighted
    
    Processing Time: 10-90 seconds depending on PDF size
    
    Example Usage:
    - Click "Try it out"
    - Click "Choose File" and select your discharge summary PDF
    - Click "Execute"
    - Wait for the patient-friendly PDF to download
    """
    
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted. Please upload a .pdf file."
        )
    
    try:
        # Read PDF content into memory
        pdf_content = await file.read()
        pdf_buffer = BytesIO(pdf_content)
        
        print(f"[pdf-converter] Received PDF: {file.filename} ({len(pdf_content)} bytes)")
        
        # Extract text from PDF using pdfplumber
        extracted_text = ""
        try:
            with pdfplumber.open(pdf_buffer) as pdf:
                total_pages = len(pdf.pages)
                print(f"[pdf-converter] Extracting text from {total_pages} pages...")
                
                for i, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text() or ""
                    extracted_text += f"\n\n--- Page {i} ---\n\n{page_text}"
                
                print(f"[pdf-converter] Extracted {len(extracted_text)} characters")
                
        except Exception as pdf_error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to extract text from PDF: {str(pdf_error)}"
            )
        
        # Validate extracted text
        if len(extracted_text.strip()) < 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PDF appears to be empty or contains very little text. "
                       "Please ensure the PDF contains a readable discharge summary."
            )
        
        # Create request object
        request_data = PatientFriendlyReportRequest(
            discharge_summary_text=extracted_text,
            patient_id=None  # Optional for PDF upload
        )
        
        # Convert to patient-friendly report
        print(f"[pdf-converter] Converting to patient-friendly report...")
        start_time = time.time()
        
        result = PatientFriendlyReportController.convert_discharge_summary(db, request_data)
        
        elapsed_time = time.time() - start_time
        print(f"[pdf-converter] Conversion complete in {elapsed_time:.2f} seconds")
        
        # Generate attractive PDF from the result
        print(f"[pdf-converter] Generating attractive PDF report...")
        pdf_file = generate_patient_friendly_pdf(result.model_dump())
        
        # Return PDF as downloadable file
        return StreamingResponse(
            iter([pdf_file.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=patient_friendly_report.pdf"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error processing PDF: {str(e)}"
        )
    finally:
        await file.close()
