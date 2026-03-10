from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from core.database import get_db
from core.security import require_admin
from services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin Analytics"])


@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    return AdminService.get_dashboard_stats(db)


@router.get("/discharge-history")
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


@router.get("/discharge/{discharge_id}/documents")
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
