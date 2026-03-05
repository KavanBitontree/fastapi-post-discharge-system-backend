from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    invoice_number = Column(String, unique=True, nullable=False)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=True)
    initial_amount = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), nullable=True, default=0.00)
    tax_amount = Column(Numeric(10, 2), nullable=True, default=0.00)
    total_amount = Column(Numeric(10, 2), nullable=False)
    bill_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    patient = relationship("Patient", back_populates="bills")
    descriptions = relationship("BillDescription", back_populates="bill", cascade="all, delete-orphan")