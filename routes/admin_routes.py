from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from core.database import get_db
from core.security import require_admin
from services.admin_service import AdminService
from schemas.admin_schemas import (
    DashboardStatsResponse,
    DischargeHistoryResponse,
    DischargeDocumentsResponse,
    AdminDischargePdfsResponse,
)

router = APIRouter(prefix="/admin", tags=["Admin Analytics"])


@router.get("/dashboard", response_model=DashboardStatsResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    return AdminService.get_dashboard_stats(db)


@router.get("/discharge-history", response_model=DischargeHistoryResponse)
def get_discharge_history(
    search: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    sort: str = Query("desc"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    return AdminService.get_discharge_history(
        db, search, page, size, sort, date_from, date_to
    )


@router.get("/discharge/{discharge_id}/documents", response_model=DischargeDocumentsResponse)
def get_discharge_documents(
    discharge_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    result = AdminService.get_discharge_documents(db, discharge_id)
    if not result:
        raise HTTPException(
            status_code=404, detail=f"Discharge {discharge_id} not found."
        )
    return result


@router.get("/discharge/{discharge_id}/pdfs", response_model=AdminDischargePdfsResponse)
def get_discharge_pdfs(
    discharge_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """
    Retrieve all three PDF Cloudinary URLs for any discharge (admin only).

    Returns:
    - **discharge_summary_url**: full hospital discharge summary PDF
    - **patient_friendly_summary_url**: simplified patient-friendly report PDF
    - **insurance_ready_url**: insurance-ready report PDF
    """
    result = AdminService.get_discharge_pdfs(db, discharge_id)
    if not result:
        raise HTTPException(
            status_code=404, detail=f"Discharge {discharge_id} not found or not completed."
        )
    return result
