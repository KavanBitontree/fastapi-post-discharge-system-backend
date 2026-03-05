import os
from pydantic_settings import BaseSettings

# Absolute path to .env so it's found regardless of cwd
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


class Settings(BaseSettings):
    NEON_DB_URL: str
    FRONTEND_URL: str
    ENV: str = "development"
    CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    CRON_SECRET: str
    GROQ_API_KEY: str
    LANGSMITH_TRACING: str
    LANGSMITH_API_KEY: str
    LANGSMITH_PROJECT: str
    LANGSMITH_ENDPOINT: str

    class Config:
        env_file = _ENV_FILE


settings = Settings()
    LANGSMITH_TRACING: bool = True
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: str
    LANGSMITH_PROJECT: str = "Medicare"


    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields in .env

# LangSmith reads directly from os.environ, not from pydantic settings.
# Setting them here ensures every entry-point (FastAPI, standalone scripts)
# has tracing enabled as soon as core.config is imported.
os.environ["LANGSMITH_TRACING"] = settings.LANGSMITH_TRACING
os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT