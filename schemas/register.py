from pydantic import BaseModel, EmailStr
from datetime import date

class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    dob: date
    gender: str
    password: str
    country_code: str
    phone_number: str

class RegisterResponse(BaseModel):
    id: int
    full_name: str
    email: str

    class Config:
        from_attributes = True # Allows SQLAlchemy model to Pydantic conversiona