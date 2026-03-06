from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base


class ReportDescription(Base):
    __tablename__ = "report_descriptions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)

    report_id = Column(Integer, ForeignKey("reports.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)

    # Test / analyte information
    test_name = Column(String(255), nullable=False)           # e.g. "Systolic Blood Pressure (SBP)"
    section = Column(String(255), nullable=True)              # e.g. "BLOOD PRESSURE MEASUREMENTS"

    normal_result = Column(String(100), nullable=True)        # Value when within normal range
    abnormal_result = Column(String(100), nullable=True)      # Value when outside normal range

    flag = Column(String(50), nullable=True)                  # "H" (High), "L" (Low), "**" (Critical), or interpretation

    units = Column(String(100), nullable=True)                # e.g. "mmHg", "mg/dL", "bpm"

    reference_range_low = Column(String(50), nullable=True)   # Lower bound of reference range
    reference_range_high = Column(String(50), nullable=True)  # Upper bound of reference range

    # Relationships
    report = relationship("Report", back_populates="descriptions")
    patient = relationship("Patient")
