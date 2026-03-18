# 1. Import Pydantic's BaseModel for data validation.
from pydantic import BaseModel, EmailStr

# 2. Request Schema: This is what the frontend sends (email/password).
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

# 3. Response Schemas
class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    is_admin: bool
    token_type: str = "bearer"

class RefreshResponse(BaseModel):
    access_token: str
    message: str
    token_type: str = "bearer"

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    # 4. Allows SQLAlchemy objects to be converted to this dictionary.
    class Config:
        from_attributes = True