from sqlalchemy.orm import Session
from models.patient import Patient
from core.security import decode_token

class AuthService:
    @staticmethod
    def get_user_by_token(db: Session, token: str):
        """Decodes the JWT from the cookie and fetches the patient record"""
        payload = decode_token(token)
        if not payload or "sub" not in payload:
            return None
        
        email = payload.get("sub")
        return db.query(Patient).filter(Patient.email == email).first()