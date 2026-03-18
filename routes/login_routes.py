from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.login import LoginRequest, RefreshRequest
from controllers.login_controller import LoginController

router = APIRouter(prefix="/login", tags=["Authentication"])

@router.post("")
def login(
    data: LoginRequest, 
    db: Session = Depends(get_db), 
    user_agent: str = Header(None, include_in_schema=False)
):
    """Handles patient/admin login and returns tokens in response body"""
    
    device = "DESKTOP" if "Mozilla" in (user_agent or "") else "MOBILE"
    
    return LoginController.process_login(db, data, device)

@router.post("/refresh")
def refresh_token(
    data: RefreshRequest,
    db: Session = Depends(get_db)
):
    """Refreshes access token and returns it in response body"""
    return LoginController.process_refresh(db, data.refresh_token)