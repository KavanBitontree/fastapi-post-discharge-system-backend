from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import get_current_user
from services.patient_profile_service import PatientProfileService
from schemas.patient_schemas import PatientUpdateRequest

router = APIRouter(prefix="/patient", tags=["Patient Self-Service"])


def _get_patient_id(current_user: dict) -> int:
    pid = current_user.get("pid")
    if pid == 0:
        raise HTTPException(
            status_code=403, detail="Admin cannot access patient endpoints."
        )
    return pid


@router.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_profile(db, patient_id)
    if not result:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return result


@router.patch("/profile")
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


@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    result = PatientProfileService.get_dashboard(db, patient_id)
    if not result:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return result


@router.get("/discharge-history")
def get_discharge_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    sort: str = Query("desc"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    patient_id = _get_patient_id(current_user)
    return PatientProfileService.get_discharge_history(db, patient_id, page, size, sort)


@router.get("/discharge/{discharge_id}/documents")
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
