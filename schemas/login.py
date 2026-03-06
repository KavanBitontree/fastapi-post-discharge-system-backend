# 1. Import Pydantic's BaseModel for data validation.
from pydantic import BaseModel, EmailStr

# 2. Request Schema: This is what the frontend sends (email/password).
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# 3. Response Schema: This is what the backend sends back after login.
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    # 4. Allows SQLAlchemy objects to be converted to this dictionary.
    class Config:
        from_attributes = True