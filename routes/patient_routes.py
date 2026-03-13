from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import get_current_user
from services.patient_profile_service import PatientProfileService
from schemas.patient_schemas import PatientUpdateRequest
from schemas.patient_profile_schemas import (
    PatientProfileResponse,
    PatientDashboardResponse,
    PatientDischargeHistoryResponse,
    PatientDischargeDocumentsResponse,
    PatientDischargePdfsResponse,
)

router = APIRouter(prefix="/patient", tags=["Patient Self-Service"])


def _get_patient_id(current_user: dict) -> int:
    pid = current_user.get("pid")
    if pid == 0:
        raise HTTPException(
            status_code=403, detail="Admin cannot access patient endpoints."
        )
    return pid


@router.get("/profile", response_model=PatientProfileResponse)
def get_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_profile(db, patient_id)
    if not result:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return result


@router.patch("/profile", response_model=PatientProfileResponse)
def update_profile(
    data: PatientUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.update_profile(db, patient_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return result


@router.get("/dashboard", response_model=PatientDashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_dashboard(db, patient_id)
    if not result:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return result


@router.get("/discharge-history", response_model=PatientDischargeHistoryResponse)
def get_discharge_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    sort: str = Query("desc"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    return PatientProfileService.get_discharge_history(db, patient_id, page, size, sort)


@router.get("/latest-discharge/pdfs", response_model=PatientDischargePdfsResponse)
def get_latest_discharge_pdfs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve PDF Cloudinary URLs for the patient's **most recent** completed discharge.

    Uses the patient identity from the JWT — no discharge ID required.

    Returns:
    - **discharge_summary_url**: full hospital discharge summary PDF
    - **patient_friendly_summary_url**: simplified patient-friendly report PDF
    - **insurance_ready_url**: insurance-ready report PDF
    """
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_latest_discharge_pdfs(db, patient_id)
    if not result:
        raise HTTPException(
            status_code=404, detail="No completed discharge record found for this patient."
        )
    return result


@router.get("/discharge/{discharge_id}/documents", response_model=PatientDischargeDocumentsResponse)
def get_discharge_documents(
    discharge_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_discharge_documents(db, patient_id, discharge_id)
    if not result:
        raise HTTPException(
            status_code=404, detail="Discharge not found or access denied."
        )
    return result


@router.get("/discharge/{discharge_id}/pdfs", response_model=PatientDischargePdfsResponse)
def get_discharge_pdfs(
    discharge_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve the Cloudinary PDF URLs for a specific discharge record.

    Returns:
    - **discharge_summary_url**: full hospital discharge summary PDF
    - **patient_friendly_summary_url**: simplified patient-friendly report PDF
    """
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_discharge_pdfs(db, patient_id, discharge_id)
    if not result:
        raise HTTPException(
            status_code=404, detail="Discharge not found or access denied."
        )
    return result
