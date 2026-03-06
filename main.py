from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from sqlalchemy import text
from core.database import engine
from core.config import settings  # noqa: F401 — also sets LangSmith os.environ vars
from fastapi.middleware.cors import CORSMiddleware
from routes import register_routes
from routes import login_routes
from routes.login_routes import login
from routes import auth_routes
from routes import logout_routes
from routes.report_routes import router as report_router
from routes.bill_routes import router as bill_router
from routes.prescription_routes import router as prescription_router

app = FastAPI(
    title="Medicare Post-Discharge System API",
    description="API for managing patient reports, bills, and medications",
    version="1.0.0",
    docs_url=None
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(register_routes.router)
app.include_router(login_routes.router)
app.include_router(auth_routes.router)
app.include_router(logout_routes.router)
router = APIRouter()
fsd.install(router)
app.include_router(router)

# Include routes
app.include_router(report_router)
app.include_router(bill_router)
app.include_router(prescription_router)


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
        return {
            "message": "Failed to connect to neon db",
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
