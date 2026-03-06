from sqlalchemy.orm import Session
from models.refresh_token import RefreshToken
from core.security import hash_token

class LogoutService:
    @staticmethod
    def revoke_session(db: Session, refresh_token: str):
        """Finds the hashed token in DB and marks it revoked"""
        if not refresh_token:
            return False
            
        hashed = hash_token(refresh_token)
        db.query(RefreshToken).filter(
            RefreshToken.refresh_token_hashed == hashed
        ).update({"is_revoked": True})
        
        db.commit()
        return True