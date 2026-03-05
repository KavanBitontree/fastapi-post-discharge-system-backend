from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from core.database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    phone_no = Column(String, nullable=True)
    speciality = Column(String, nullable=True)

    # Relationships
    medications = relationship("Medication", back_populates="doctor")
    patients = relationship("PatientDoctor", back_populates="doctor")
