"""
patient_friendly_report_schemas.py
-----------------------------------
Schemas for patient-friendly discharge summary conversion.
"""

from pydantic import BaseModel, Field
from typing import Optional


class PatientFriendlyReportRequest(BaseModel):
    """Request schema for converting discharge summary to patient-friendly format."""
    
    discharge_summary_text: str = Field(
        ...,
        description="Full text of the discharge summary (15-16 pages)",
        min_length=100
    )
    patient_id: Optional[int] = Field(
        None,
        description="Optional patient ID for tracking"
    )


class PatientFriendlyReportResponse(BaseModel):
    """Response schema for patient-friendly report."""
    
    summary: str = Field(
        ...,
        description="Patient-friendly 1-page summary"
    )
    key_points: list[str] = Field(
        default_factory=list,
        description="Key takeaways in bullet points"
    )
    medications: list[str] = Field(
        default_factory=list,
        description="Simplified medication list"
    )
    precautions: list[str] = Field(
        default_factory=list,
        description="Important precautions and restrictions"
    )
    follow_up_instructions: str = Field(
        default="",
        description="What patient needs to do next"
    )
    warning_signs: list[str] = Field(
        default_factory=list,
        description="When to seek immediate medical attention"
    )
    original_length_chars: int = Field(
        ...,
        description="Original document length"
    )
    summary_length_chars: int = Field(
        ...,
        description="Summary length"
    )
    processing_time_seconds: float = Field(
        ...,
        description="Time taken to process"
    )
