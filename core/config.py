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

# LangSmith tracing configuration (latest approach from LangSmith docs)
# Set environment variables for LangSmith tracing
# See: https://docs.smith.langchain.com/observability/how_to_guides/trace_with_langgraph
if settings.LANGSMITH_TRACING.lower() == "true":
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT