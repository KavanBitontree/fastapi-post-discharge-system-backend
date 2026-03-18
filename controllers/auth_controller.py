from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session
from services.auth_service import AuthService

class AuthController:
    @staticmethod
    def get_current_user(request: Request, db: Session):

        # Try to get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Not authenticated"
            )
        
        token = auth_header.split(" ")[1]

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