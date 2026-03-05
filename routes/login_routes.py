from fastapi import APIRouter, Depends, Header, Response # Added Response
from sqlalchemy.orm import Session
from core.database import get_db
from schemas.login import LoginRequest
from controllers.login_controller import LoginController

router = APIRouter(prefix="/login", tags=["Authentication"])

@router.post("")
def login(
    data: LoginRequest, 
    response: Response, 
    db: Session = Depends(get_db), 
    user_agent: str = Header(None)
):
    """Handles patient/admin login and sets HttpOnly cookies"""
    
    device = "DESKTOP" if "Mozilla" in (user_agent or "") else "MOBILE"
    
    return LoginController.process_login(db, data, device, response)

@router.post("/refresh")
def refresh_token(
    data: dict, # Expecting {"refresh_token": "..."}
    response: Response, 
    db: Session = Depends(get_db)
):
    # Pass to controller to verify the refresh token and set a new access cookie
    return LoginController.process_refresh(db, data.get("refresh_token"), response)