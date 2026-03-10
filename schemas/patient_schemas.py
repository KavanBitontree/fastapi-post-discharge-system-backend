from pydantic import BaseModel
from typing import Optional
from datetime import date


class PatientUpdateRequest(BaseModel):
    phone_number: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    address: Optional[str] = None

    class Config:
        from_attributes = True
