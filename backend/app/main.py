from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.bullion import router as bullion_router
from app.api.routes.data_monitor import router as data_monitor_router
from app.api.routes.kjpl import router as kjpl_router
from app.api.routes.market import router as market_router
from app.api.routes.prediction import router as prediction_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.news import router as news_router
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.services.data_service import init_database
from app.services.kjpl.persistence import seed_bullion_metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    try:
        seed_bullion_metadata()
    except Exception as e:
        print(f"[LIFESPAN] Seed metadata note: {e}")
    try:
        start_scheduler()
    except Exception as e:
        print(f"[LIFESPAN] Scheduler start note: {e}")
    yield
    try:
        stop_scheduler()
    except Exception:
        pass


app = FastAPI(
    title="VMD Bullion Intelligence Terminal",
    description="Bloomberg-inspired Institutional Indian Bullion Intelligence Terminal",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bullion_router)
app.include_router(data_monitor_router)
app.include_router(kjpl_router)
app.include_router(market_router)
app.include_router(prediction_router)
app.include_router(portfolio_router)
app.include_router(alerts_router)
app.include_router(news_router)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "VMD Bullion API", "version": "1.0.0"}
