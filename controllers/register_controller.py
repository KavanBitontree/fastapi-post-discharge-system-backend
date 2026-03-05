from fastapi import HTTPException, status, Response
from sqlalchemy.orm import Session
from services.register_service import RegisterService
from core.security import create_tokens, hash_token # Ensure hash_token is imported
from models.refresh_token import RefreshToken
from datetime import datetime, timezone
from core.enums import DeviceType

class RegisterController:
    @staticmethod
    def process_registration(db: Session, data, response: Response):

        existing_user = RegisterService.get_patient_by_email(db, data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Email is already registered"
            )
        
        new_patient = RegisterService.create_new_patient(db, data)
        
        access_token, refresh_token, expires_at= create_tokens(email=new_patient.email,pid=new_patient.id)
        
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            samesite="lax",
            secure=False, # True in Production
            max_age=30  
        )
        db_refresh_token = RefreshToken(
            patient_id=new_patient.id,
            refresh_token_hashed=hash_token(refresh_token), 
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
            device_type=DeviceType.DESKTOP, # You can detect this from User-Agent if needed
            is_revoked=False
        )
        db.add(db_refresh_token)
        db.commit()
        
        return {
            "id": new_patient.id,
            "full_name": new_patient.full_name,
            "email": new_patient.email,
            "refresh_token": refresh_token
        }