"""
patient_friendly_report_controller.py
--------------------------------------
Controller for converting discharge summaries to patient-friendly reports.
"""

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
import time
from schemas.patient_friendly_report_schemas import (
    PatientFriendlyReportRequest,
    PatientFriendlyReportResponse
)
from services.llm_validators.llm_discharge_summary_converter import (
    convert_discharge_summary_to_patient_friendly
)


class PatientFriendlyReportController:
    
    @staticmethod
    def convert_discharge_summary(
        db: Session,
        request_data: PatientFriendlyReportRequest
    ) -> PatientFriendlyReportResponse:
        """
        Convert a complex discharge summary into a patient-friendly 1-page report.
        
        Parameters
        ----------
        db : Session
            Database session
        request_data : PatientFriendlyReportRequest
            Request containing discharge summary text
        
        Returns
        -------
        PatientFriendlyReportResponse
            Patient-friendly report with summary, key points, etc.
        """
        
        # Validate input
        if len(request_data.discharge_summary_text) < 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Discharge summary text is too short. Minimum 100 characters required."
            )
        
        # Track processing time
        start_time = time.time()
        
        try:
            # Convert the discharge summary
            result = convert_discharge_summary_to_patient_friendly(
                discharge_text=request_data.discharge_summary_text
            )
            
            processing_time = time.time() - start_time
            
            # Add metadata
            result["original_length_chars"] = len(request_data.discharge_summary_text)
            result["summary_length_chars"] = len(result["summary"])
            result["processing_time_seconds"] = round(processing_time, 2)
            
            return PatientFriendlyReportResponse(**result)
            
        except ValueError as ve:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to convert discharge summary: {str(ve)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error during conversion: {str(e)}"
            )
