from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
 
 
class DischargeHistory(Base):
    __tablename__ = "discharge_history"
 
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    discharge_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
 
    # Processing state
    status = Column(String(20), nullable=False, default="pending")   # pending | processing | completed | failed
    processed_reports = Column(Integer, nullable=False, default=0)
    processed_bills = Column(Integer, nullable=False, default=0)
    processed_prescriptions = Column(Integer, nullable=False, default=0)
    discharge_summary_url = Column(String, nullable=True)
    patient_friendly_summary_url = Column(String, nullable=True)
    insurance_ready_url = Column(String, nullable=True)

    # Relationships
    patient = relationship("Patient", back_populates="discharge_histories")
    bills = relationship("Bill", back_populates="discharge", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="discharge", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="discharge", cascade="all, delete-orphan")
    doctors = relationship("PatientDoctor", back_populates="discharge", cascade="all, delete-orphan")
    telegram_sessions = relationship("TelegramSession", back_populates="discharge", cascade="all, delete-orphan")
    chat_history = relationship("ChatHistory", back_populates="discharge", cascade="all, delete-orphan")
 
