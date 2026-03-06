from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from core.database import get_db
from controllers.auth_controller import AuthController
from core.security import get_current_user  # <--- Add this import!

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):

    is_admin = current_user.get("pid") == 0
    
    return {
        "pid": current_user.get("pid"),
        "email": current_user.get("sub"),
        "full_name": "Administrator" if is_admin else current_user.get("full_name"),
        "is_admin": is_admin  
    }