from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from core.database import get_db
from core.security import get_current_user, require_admin
from controllers.fetch_patient_controller import FetchPatientController

router = APIRouter(prefix="/admin/patients", tags=["Admin Patient Management"])
@router.get("")
def get_patients(
    search: str = Query(None), 
    page: int = Query(1), 
    size: int = Query(5), 
    sort: str = Query("asc"), 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user),
    admin: dict = Depends(require_admin)
):
    return FetchPatientController.list_patients(db, search, page, size, sort)

@router.get("/{patient_id}")
def get_patient_detail(
    patient_id: int, 
    db: Session = Depends(get_db), 
    admin: dict = Depends(require_admin)
):
    """Admin Only: Get specific patient profile"""
    return FetchPatientController.get_details(db, patient_id)