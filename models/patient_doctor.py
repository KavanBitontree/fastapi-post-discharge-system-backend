from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base


class PatientDoctor(Base):
    """Many-to-many relationship table between patients and doctors"""
    __tablename__ = "patient_doctor"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)

    # Relationships
    patient = relationship("Patient", back_populates="doctors")
    doctor = relationship("Doctor", back_populates="patients")
