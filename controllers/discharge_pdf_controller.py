"""
controllers/discharge_pdf_controller.py
-----------------------------------------
Controller for fetching discharge-generated PDF URLs.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from schemas.discharge_schemas import DischargePdfsResponse
from services.discharge_pdf_service import DischargePdfService


class DischargePdfController:

    @staticmethod
    def get_pdfs_by_discharge(db: Session, discharge_id: int) -> DischargePdfsResponse:
        """
        Return all Cloudinary PDF URLs stored against a discharge record.

        Raises 404 if the discharge record does not exist.
        Raises 404 if the discharge hasn't been processed yet (no URLs stored).
        """
        discharge = DischargePdfService.get_by_id(db, discharge_id)
        if not discharge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Discharge id={discharge_id} not found.",
            )

        has_any_pdf = any([
            discharge.discharge_summary_url,
            discharge.patient_friendly_summary_url,
            discharge.insurance_ready_url,
        ])
        if not has_any_pdf:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No PDFs have been generated for discharge id={discharge_id} yet. "
                    "Process the discharge documents first."
                ),
            )

        return DischargePdfsResponse(
            discharge_id=discharge.id,
            patient_id=discharge.patient_id,
            status=discharge.status,
            discharge_summary_url=discharge.discharge_summary_url,
            patient_friendly_summary_url=discharge.patient_friendly_summary_url,
            insurance_ready_url=discharge.insurance_ready_url,
        )

    @staticmethod
    def get_pdfs_by_patient(db: Session, patient_id: int) -> DischargePdfsResponse:
        """
        Return PDF URLs for the most recent discharge record of a patient.

        Raises 404 if no discharge record exists for the patient.
        """
        discharge = DischargePdfService.get_latest_for_patient(db, patient_id)
        if not discharge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No discharge record found for patient id={patient_id}.",
            )

        has_any_pdf = any([
            discharge.discharge_summary_url,
            discharge.patient_friendly_summary_url,
            discharge.insurance_ready_url,
        ])
        if not has_any_pdf:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No PDFs have been generated for patient id={patient_id}'s latest discharge yet. "
                    "Process the discharge documents first."
                ),
            )

        return DischargePdfsResponse(
            discharge_id=discharge.id,
            patient_id=discharge.patient_id,
            status=discharge.status,
            discharge_summary_url=discharge.discharge_summary_url,
            patient_friendly_summary_url=discharge.patient_friendly_summary_url,
            insurance_ready_url=discharge.insurance_ready_url,
        )
