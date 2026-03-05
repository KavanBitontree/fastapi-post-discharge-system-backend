from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base


class MedicationSchedule(Base):
    __tablename__ = "medication_schedules"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, unique=True, index=True)
    
    # Timing flags for when to take medication
    before_breakfast = Column(Boolean, nullable=True, default=False)
    after_breakfast = Column(Boolean, nullable=True, default=False)
    before_lunch = Column(Boolean, nullable=True, default=False)
    after_lunch = Column(Boolean, nullable=True, default=False)
    before_dinner = Column(Boolean, nullable=True, default=False)
    after_dinner = Column(Boolean, nullable=True, default=False)
    
    # Notification tracking
    latest_notified_at = Column(DateTime(timezone=True), nullable=True)
    next_notify_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    medication = relationship("Medication", back_populates="schedule")
