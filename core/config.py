from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    NEON_DB_URL: str
    FRONTEND_URL: str = "http://localhost:5173"
    ENV: str = "development"
    CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    CRON_SECRET: str

    
    class Config:
        env_file = ".env"

settings = Settings()