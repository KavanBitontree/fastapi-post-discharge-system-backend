from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    email = Column(String, nullable=True, unique=True,index=True)
    password_hash = Column(String, nullable=True)  # For authentication if needed
    dob = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    address = Column(String, nullable=True)
    discharge_date = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    # Relationships
    reports = relationship("Report", back_populates="patient", cascade="all, delete-orphan")
    bills = relationship("Bill", back_populates="patient", cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="patient", cascade="all, delete-orphan")
    doctors = relationship("PatientDoctor", back_populates="patient", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="patient", cascade="all, delete-orphan")
    telegram_sessions = relationship("TelegramSession", back_populates="patient", cascade="all, delete-orphan")
    chat_history = relationship("ChatHistory", back_populates="patient", cascade="all, delete-orphan")