from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from core.database import get_db
from  controllers.logout_controller import LogoutController

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/logout")
def logout(
    response: Response, 
    data: dict, # Expecting {"refresh_token": "..."}
    db: Session = Depends(get_db)
):
    """Endpoint to revoke session and clear cookies"""
    token = data.get("refresh_token")
    return LogoutController.execute_logout(db, token, response)