from fastapi import Response
from sqlalchemy.orm import Session
from services.logout_service import LogoutService

class LogoutController:
    @staticmethod
    def execute_logout(db: Session, refresh_token: str, response: Response):
        response.delete_cookie(
            key="access_token",
            httponly=True,
            samesite="none",
            secure=True  # Set to True in production (HTTPS)
        )

        # 2. Invalidate the refresh token in the database
        LogoutService.revoke_session(db, refresh_token)

        return {"message": "Logged out successfully"}