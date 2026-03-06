from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session
from services.auth_service import AuthService

class AuthController:
    @staticmethod
    def get_current_user(request: Request, db: Session):

        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Not authenticated"
            )

        user = AuthService.get_user_by_token(db, token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid session or user not found"
            )

        return {
            "full_name": user.full_name,
            "email": user.email,
            "dob": user.dob,
            "gender": user.gender
        }