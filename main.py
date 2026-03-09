from contextlib import asynccontextmanager

from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from sqlalchemy import text

from core.database import engine
from core.config import settings  # noqa: F401 — also sets LangSmith os.environ vars
from core.scheduler import start_scheduler, stop_scheduler
import models  # noqa: F401 — registers all mappers (including TelegramSession) on startup
from services.telegram.bot import start_polling, stop_polling

from fastapi.middleware.cors import CORSMiddleware
from routes.report_routes import router as report_router
from routes.bill_routes import router as bill_router
from routes.prescription_routes import router as prescription_router
from routes.reminder_routes import router as reminder_router   # ← new
from routes.chat_routes import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    start_scheduler()   # starts all 6 cron reminder jobs in background thread
    start_polling()     # starts Telegram bot long-polling thread
    yield
    stop_scheduler()
    stop_polling()


app = FastAPI(
    title="Medicare Post-Discharge System API",
    description="API for managing patient reports, bills, and medications",
    version="1.0.0",
    docs_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()
fsd.install(router)
app.include_router(router)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(report_router)
app.include_router(bill_router)
app.include_router(prescription_router)
app.include_router(reminder_router)   # ← new: /reminders/trigger
app.include_router(chat_router)        # POST /chat


@app.get("/")
async def hello():
    return {"message": "Hello, World!"}


@app.get("/db-check")
async def db_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"message": "Connected to neon db"}
    except Exception as e:
        return {"message": "Failed to connect to neon db", "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)