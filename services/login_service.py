from sqlalchemy.orm import Session
from models.patient import Patient
from models.refresh_token import RefreshToken
from core.security import verify_password, create_tokens, hash_token
from datetime import datetime, timezone

class LoginService:
    @staticmethod
    def authenticate_patient(db: Session, email: str, password: str):
        patient = db.query(Patient).filter(Patient.email == email).first()
        if not patient or not verify_password(password, patient.password_hash):
            return None
        return patient

    @staticmethod
    def handle_single_device_login(db: Session, patient, device_type: str):

        db.query(RefreshToken).filter(
            RefreshToken.patient_id == patient.id,
            RefreshToken.is_revoked == False
        ).update({"is_revoked": True})
        
        access_token, refresh_token, expires_at = create_tokens(patient.email, patient.id)
        
        db_token = RefreshToken(
            patient_id=patient.id,
            refresh_token_hashed=hash_token(refresh_token),
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
            device_type="DESKTOP", 
            is_revoked=False
        )
        db.add(db_token)
        db.commit()
        
        return access_token, refresh_token

    @staticmethod
    def handle_admin_login(db: Session, device_type: str):
        ADMIN_ID = 0
        ADMIN_EMAIL = "admin@medicare.com"
        
        db.query(RefreshToken).filter(
            RefreshToken.patient_id == ADMIN_ID,
            RefreshToken.is_revoked == False
        ).update({"is_revoked": True})
        
        access_token, refresh_token, expires_at = create_tokens(ADMIN_EMAIL, ADMIN_ID)
        
        db_token = RefreshToken(
            patient_id=ADMIN_ID,
            refresh_token_hashed=hash_token(refresh_token),
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
            device_type="DESKTOP",
            is_revoked=False
        )
        db.add(db_token)
        db.commit()
        
        return access_token, refresh_token