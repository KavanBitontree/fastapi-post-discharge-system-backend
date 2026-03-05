from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)

    report_date = Column(DateTime(timezone=True), nullable=True)
    collection_date = Column(DateTime(timezone=True), nullable=True)
    received_date = Column(DateTime(timezone=True), nullable=True)

    specimen_type = Column(String(255), nullable=True)   # e.g. "Whole Blood / Serum / Urine"
    status = Column(String(100), nullable=True)           # e.g. "ROUTINE", "FINAL"
    report_url = Column(Text, nullable=True)              # Cloudinary / storage URL of the PDF

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    patient = relationship("Patient", back_populates="reports")
    descriptions = relationship("ReportDescription", back_populates="report", cascade="all, delete-orphan")
