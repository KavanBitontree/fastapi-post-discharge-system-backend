from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import date
import re

VALID_GENDERS = {"Male", "Female", "Other", "Prefer not to say"}
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class PatientUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    address: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Name must be at least 3 characters")
        if not re.match(r"^[a-zA-Z\s]+$", v):
            raise ValueError("Name must contain only alphabets and spaces")
        return v

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        if not _PHONE_RE.match(v):
            raise ValueError("Enter a valid phone number (7–15 digits, optional leading +)")
        return v

    @field_validator("dob")
    @classmethod
    def validate_dob(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return v
        today = date.today()
        if v > today:
            raise ValueError("Date of birth cannot be in the future")
        age_days = (today - v).days
        if age_days > 150 * 365:
            raise ValueError("Age cannot exceed 150 years")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        if v not in VALID_GENDERS:
            raise ValueError(f"Gender must be one of: {', '.join(sorted(VALID_GENDERS))}")
        return v

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        if len(v.strip()) < 5:
            raise ValueError("Address must be at least 5 characters")
        return v

    class Config:
        from_attributes = True
