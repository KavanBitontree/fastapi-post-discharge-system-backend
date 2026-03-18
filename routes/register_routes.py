from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.register import RegisterRequest
from controllers.register_controller import RegisterController

router = APIRouter(prefix="/register", tags=["Registration"])

@router.post("", response_model=dict)
def register_patient(data: RegisterRequest, db: Session = Depends(get_db)):
    """Register new patient and return tokens in response body"""
    return RegisterController.process_registration(db, data)