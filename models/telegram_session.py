"""
Telegram Session Model
----------------------
Manages Telegram bot authentication sessions with OTP verification.
"""

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.enums import SessionStatus


class TelegramSession(Base):
    __tablename__ = "telegram_sessions"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)  # Nullable until verified
    session_status = Column(SQLEnum(SessionStatus), nullable=False, default=SessionStatus.NEW)
    telegram_id = Column(String, nullable=False, unique=True, index=True)  # Telegram user ID
    phone_number = Column(String, nullable=True)  # Phone number for verification
    otp = Column(String, nullable=True)  # One-time password
    otp_created_at = Column(DateTime(timezone=True), nullable=True)  # When OTP was generated
    otp_expires_at = Column(DateTime(timezone=True), nullable=True)  # When OTP expires
    verified_at = Column(DateTime(timezone=True), nullable=True)  # When session was verified
    attempts = Column(Integer, nullable=False, default=3)  # Remaining OTP attempts
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    # Relationships
    patient = relationship("Patient", back_populates="telegram_sessions")

    def __repr__(self):
        return f"<TelegramSession(id={self.id}, telegram_id={self.telegram_id}, status={self.session_status})>"