from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from core.enums import MedicineForm


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    discharge_id = Column(Integer, ForeignKey("discharge_history.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    drug_name = Column(String, nullable=False)
    dosage = Column(String, nullable=False)  # e.g., "1 tablet", "5ml"
    frequency_of_dose_per_day = Column(Integer, nullable=False)  # e.g., 1, 2, 3 times per day
    dosing_days = Column(Integer, nullable=True)  # Total days to take medication
    recurrence_id = Column(Integer, ForeignKey("recurrence_types.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    strength = Column(String, nullable=True)  # e.g., "500mg", "10mg/5ml"
    form_of_medicine = Column(SQLEnum(MedicineForm), nullable=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True, index=True)
    prescription_date = Column(Date, nullable=True)

    # Relationships
    discharge = relationship("DischargeHistory", back_populates="medications")
    doctor = relationship("Doctor", back_populates="medications")
    recurrence = relationship("RecurrenceType", back_populates="medications", cascade="all, delete-orphan", single_parent=True)
    schedule = relationship("MedicationSchedule", back_populates="medication", uselist=False, cascade="all, delete-orphan")
