from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from core.database import get_db
from controllers.logout_controller import LogoutController
from core.security import get_current_user
from schemas.login import LogoutRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/logout")
def logout(
    response: Response, 
    data: LogoutRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Endpoint to revoke session and clear cookies"""
    token = data.refresh_token
    return LogoutController.execute_logout(db, token, response)