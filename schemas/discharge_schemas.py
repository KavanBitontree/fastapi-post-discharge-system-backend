"""
schemas/discharge_schemas.py
-----------------------------
Pydantic schemas for discharge PDF retrieval responses.
"""

from pydantic import BaseModel
from typing import Optional


class DischargePdfsResponse(BaseModel):
    """Response schema containing all generated PDF Cloudinary URLs for a discharge record."""

    discharge_id: int
    patient_id: int
    status: str
    discharge_summary_url: Optional[str] = None
    patient_friendly_summary_url: Optional[str] = None
    insurance_ready_url: Optional[str] = None

    model_config = {"from_attributes": True}
