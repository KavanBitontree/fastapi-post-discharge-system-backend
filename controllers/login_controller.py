from urllib import response

from fastapi import HTTPException, status, Response
from sqlalchemy.orm import Session
from services.login_service import LoginService
from core.security import create_tokens, decode_token, hash_token, create_access_token
from models.refresh_token import RefreshToken 
from datetime import datetime, timezone

# Hardcoded Admin Credentials
ADMIN_EMAIL = "admin@medicare.com"
ADMIN_PASS = "Admin@123"

class LoginController:
    @staticmethod
    def process_login(db: Session, login_data, device_type: str, response: Response):

        if login_data.email == ADMIN_EMAIL and login_data.password == ADMIN_PASS:
            access_token, refresh_token = LoginService.handle_admin_login(db, device_type)
            is_admin = True
        else:
            patient = LoginService.authenticate_patient(db, login_data.email, login_data.password)
            if not patient:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )
            access_token, refresh_token = LoginService.handle_single_device_login(db, patient, device_type)
            is_admin = False

        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            samesite="none",
            secure=True, 
            max_age=900
        )
        
        return {"refresh_token": refresh_token, "is_admin": is_admin}
    
    @staticmethod
    def process_refresh(db: Session, refresh_token: str, response: Response):

        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        #Get the hash to look up the active session
        hashed = hash_token(refresh_token)
        
        db_token = db.query(RefreshToken).filter(
            RefreshToken.refresh_token_hashed == hashed,
            RefreshToken.is_revoked == False
        ).first()

        if not db_token or db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Token expired or revoked")

        # Only generate a new access token, keep it linked to the existing 'hashed' DB row
        access_token = create_access_token(payload.get("sub"), payload.get("pid"), hashed)

        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            samesite="none",
            secure=True,
            max_age=900 
        )
        return {"message": "Token refreshed"}