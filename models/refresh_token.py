from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.enums import DeviceType


class RefreshToken(Base):
    """Refresh tokens for single device login per patient"""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    refresh_token_hashed = Column(String, nullable=False, unique=True)
    is_revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    device_type = Column(SQLEnum(DeviceType), nullable=True)

    # Relationships
    patient = relationship("Patient", back_populates="refresh_tokens")
