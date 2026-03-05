from sqlalchemy import Column, Integer, String, Date
from sqlalchemy.orm import relationship
from core.database import Base


class RecurrenceType(Base):
    __tablename__ = "recurrence_types"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)  # e.g., "daily", "every_n_days", "cyclic"
    every_n_days = Column(Integer, nullable=True)  # For "every N days" pattern
    start_date_for_every_n_days = Column(Date, nullable=True)  # Start date for every_n_days pattern
    cycle_take_days = Column(Integer, nullable=True)  # Days to take medication in a cycle
    cycle_skip_days = Column(Integer, nullable=True)  # Days to skip medication in a cycle

    # Relationships
    medications = relationship("Medication", back_populates="recurrence")
