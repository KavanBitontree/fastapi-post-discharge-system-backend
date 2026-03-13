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
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_SECRET: str = ""  # secret_token for verifying webhook requests
    BACKEND_URL: str = ""  # e.g. https://your-app.vercel.app — used to register Telegram webhook
    HF_TOKEN: str  # HuggingFace token for image-to-text model
    LANGSMITH_TRACING: str
    LANGSMITH_API_KEY: str
    LANGSMITH_PROJECT: str
    LANGSMITH_ENDPOINT: str
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_FROM_NUMBER: str

    # ICD-10 RAG
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "icd10cm-2026"
    PINECONE_NAMESPACE: str = "icd10cm_2026"
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash"

    class Config:
        env_file = _ENV_FILE
        extra = "ignore"  # ignore unknown vars like HF_HUB_DISABLE_SYMLINKS_WARNING


settings = Settings()

# LangSmith tracing configuration (latest approach from LangSmith docs)
# Set environment variables for LangSmith tracing
# See: https://docs.smith.langchain.com/observability/how_to_guides/trace_with_langgraph
if settings.LANGSMITH_TRACING.lower() == "true":
    os.environ["LANGCHAIN_TRACING_V2"] = "true"  # Updated key name
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
    
    # Also set legacy keys for compatibility
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT