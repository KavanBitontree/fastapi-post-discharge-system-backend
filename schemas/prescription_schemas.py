"""
Prescription Pydantic Schemas
------------------------------
Pydantic models for LLM-based prescription extraction.
Used for structured output validation.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class MedicationSchedule(BaseModel):
    """Medication schedule."""
    before_breakfast: bool = False
    after_breakfast: bool = False
    before_lunch: bool = False
    after_lunch: bool = False
    before_dinner: bool = False
    after_dinner: bool = False


class MedicationRecurrence(BaseModel):
    """Medication recurrence pattern."""
    type: str = "daily"  # daily, every_n_days, cyclic
    every_n_days: Optional[int] = None
    start_date_for_every_n_days: Optional[str] = None
    cycle_take_days: Optional[int] = None
    cycle_skip_days: Optional[int] = None


class Medication(BaseModel):
    """Individual medication."""
    drug_name: str
    strength: Optional[str] = None
    form_of_medicine: Optional[str] = None
    dosage: str = "1"
    frequency_of_dose_per_day: int = 1
    dosing_days: Optional[int] = None
    prescription_date: Optional[str] = None
    recurrence: MedicationRecurrence = Field(default_factory=MedicationRecurrence)
    schedule: MedicationSchedule = Field(default_factory=MedicationSchedule)


class PrescriptionHeader(BaseModel):
    """Prescription header information."""
    rx_number: Optional[str] = None
    rx_date: Optional[str] = None
    patient_phone: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_email: Optional[str] = None
    doctor_speciality: Optional[str] = None


class ValidatedPrescription(BaseModel):
    """Complete validated prescription."""
    header: PrescriptionHeader
    medications: List[Medication]
