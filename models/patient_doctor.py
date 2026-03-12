from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base


class PatientDoctor(Base):
    """Many-to-many relationship table between patients and doctors"""
    __tablename__ = "patient_doctor"

    id = Column(Integer, primary_key=True, index=True)
    discharge_id = Column(Integer, ForeignKey("discharge_history.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)

    # Relationships
    discharge = relationship("DischargeHistory", back_populates="doctors")
    doctor = relationship("Doctor", back_populates="patients")
