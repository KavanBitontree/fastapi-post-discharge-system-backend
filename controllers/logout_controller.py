from sqlalchemy.orm import Session
from services.logout_service import LogoutService

class LogoutController:
    @staticmethod
    def execute_logout(db: Session, refresh_token: str):
        # Invalidate the refresh token in the database
        LogoutService.revoke_session(db, refresh_token)

        return {"message": "Logged out successfully"}