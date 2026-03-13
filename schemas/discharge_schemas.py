"""
schemas/discharge_schemas.py
-----------------------------
Pydantic schemas for discharge PDF retrieval responses.
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any


class DischargePdfsResponse(BaseModel):
    """Response schema containing all generated PDF Cloudinary URLs for a discharge record."""

    discharge_id: int
    patient_id: int
    status: str
    discharge_summary_url: Optional[str] = None
    patient_friendly_summary_url: Optional[str] = None
    insurance_ready_url: Optional[str] = None

    model_config = {"from_attributes": True}


class DischargeErrorResponse(BaseModel):
    """Response schema for discharge processing errors."""
    
    message: str
    discharge_id: int
    status: str
    error_type: str
    error_title: str
    error: str
    progress: Dict[str, int]
    failed_at: Dict[str, Any]


class DischargeStatusResponse(BaseModel):
    """Response schema for discharge status polling."""
    
    discharge_id: int
    patient_id: int
    discharge_date: Optional[str] = None
    status: str
    processed: Dict[str, int]
    error: Optional[Dict[str, Any]] = None  # Present only when status="failed"


class DischargeValidationResponse(BaseModel):
    """Response schema for discharge file validation."""
    
    valid: bool
    patient_id: int
    file_counts: Dict[str, int]
