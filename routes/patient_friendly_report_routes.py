"""
patient_friendly_report_routes.py
----------------------------------
API endpoint for converting discharge summary PDFs to patient-friendly reports.
"""

from fastapi import APIRouter, Depends, status, UploadFile, File, HTTPException, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.patient_friendly_report_schemas import (
    PatientFriendlyReportRequest,
    PatientFriendlyReportResponse
)
from controllers.patient_friendly_report_controller import PatientFriendlyReportController
from services.pdf_generator import generate_patient_friendly_pdf
from services.storage.cloudinary_storage import upload_medical_pdf
from models.discharge_history import DischargeHistory
import pdfplumber
from io import BytesIO
import time


router = APIRouter(
    prefix="/api/patient-friendly-report",
    tags=["Patient Friendly Reports"]
)


@router.post(
    "/convert-pdf/{patient_id}",
    status_code=status.HTTP_200_OK
)
async def convert_discharge_summary_pdf(
    patient_id: int = Path(..., description="Patient ID"),
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
    5. Upload original discharge summary to Cloudinary
    6. Upload patient-friendly report to Cloudinary
    7. Find latest discharge history for patient
    8. Save both URLs to database
    9. Return Cloudinary links
    
    Returns:
    - Cloudinary URL of original discharge summary
    - Cloudinary URL of patient-friendly PDF report
    - Patient-friendly PDF report (1 page, easy to read)
    - Summary (500-700 words in simple language)
    - Key points (3-5 bullet points)
    - Medications in simple terms
    - Follow-up instructions
    - Warning signs highlighted
    
    Processing Time: 10-90 seconds depending on PDF size
    
    Example Usage:
    - Click "Try it out"
    - Enter patient_id in URL
    - Click "Choose File" and select your discharge summary PDF
    - Click "Execute"
    - Get Cloudinary links and download the patient-friendly PDF
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
            patient_id=patient_id
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
        
        # Upload both PDFs to Cloudinary
        print(f"[pdf-converter] Uploading PDFs to Cloudinary...")
        try:
            # 1. Upload original discharge summary PDF
            print(f"[pdf-converter] Uploading original discharge summary...")
            pdf_buffer.seek(0)  # Reset buffer position
            discharge_summary_result = upload_medical_pdf(
                file=pdf_buffer,
                filename=f"discharge_summary_patient_{patient_id}.pdf",
                document_type="report",
                patient_id=patient_id
            )
            discharge_summary_url = discharge_summary_result["secure_url"]
            print(f"[pdf-converter] Discharge summary uploaded: {discharge_summary_url}")
            
            # 2. Upload patient-friendly report PDF
            print(f"[pdf-converter] Uploading patient-friendly report...")
            pdf_file.seek(0)  # Reset buffer position
            patient_friendly_result = upload_medical_pdf(
                file=pdf_file,
                filename=f"patient_friendly_report_patient_{patient_id}.pdf",
                document_type="report",
                patient_id=patient_id
            )
            patient_friendly_url = patient_friendly_result["secure_url"]
            print(f"[pdf-converter] Patient-friendly report uploaded: {patient_friendly_url}")
            
            # Find latest discharge history for this patient
            print(f"[pdf-converter] Finding latest discharge history for patient {patient_id}...")
            latest_discharge = db.query(DischargeHistory).filter(
                DischargeHistory.patient_id == patient_id
            ).order_by(DischargeHistory.created_at.desc()).first()
            
            if latest_discharge:
                # Save both URLs to database
                latest_discharge.discharge_summary_url = discharge_summary_url
                latest_discharge.patient_friendly_summary_url = patient_friendly_url
                db.commit()
                print(f"[pdf-converter] Saved both URLs to discharge history {latest_discharge.id}")
                print(f"  - discharge_summary_url: {discharge_summary_url}")
                print(f"  - patient_friendly_summary_url: {patient_friendly_url}")
            else:
                print(f"[pdf-converter] Warning: No discharge history found for patient {patient_id}")
            
            # Return response with both Cloudinary URLs
            return {
                "discharge_summary_url": discharge_summary_url,
                "discharge_summary_public_id": discharge_summary_result["public_id"],
                "patient_friendly_url": patient_friendly_url,
                "patient_friendly_public_id": patient_friendly_result["public_id"],
                "patient_id": patient_id,
                "discharge_id": latest_discharge.id if latest_discharge else None,
                "summary": result.summary,
                "key_points": result.key_points,
                "medications": result.medications,
                "precautions": result.precautions,
                "follow_up_instructions": result.follow_up_instructions,
                "warning_signs": result.warning_signs,
                "processing_time_seconds": result.processing_time_seconds,
                "original_length_chars": result.original_length_chars,
                "summary_length_chars": result.summary_length_chars,
            }
            
        except Exception as cloudinary_error:
            print(f"[pdf-converter] Cloudinary upload failed: {str(cloudinary_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload PDFs to Cloudinary: {str(cloudinary_error)}"
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
