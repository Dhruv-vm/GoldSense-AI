from __future__ import annotations

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.bullion import router as bullion_router
from app.api.routes.data_monitor import router as data_monitor_router
from app.api.routes.kjpl import router as kjpl_router
from app.api.routes.market import router as market_router
from app.api.routes.prediction import router as prediction_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.news import router as news_router
from app.db.session import ENVIRONMENT, check_database_health
from app.services.data_service import init_database
from app.services.kjpl.persistence import seed_bullion_metadata


def _get_allowed_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
    return origins or ["http://localhost:3000"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Single-writer rule: FastAPI serves API & SSE streams only; persistent DB writing scrapers are separate.
    if ENVIRONMENT != "production":
        init_database()
        try:
            seed_bullion_metadata()
        except Exception as e:
            print(f"[LIFESPAN] Metadata seed note: {e}")
    else:
        db_health = check_database_health()
        if not db_health.get("connected"):
            raise RuntimeError(f"[LIFESPAN] Production database connection check failed: {db_health.get('error')}")

    # Own the five-city live collector and its in-memory cache
    enable_collector_env = os.environ.get("ENABLE_FASTAPI_LIVE_COLLECTOR")
    should_run_collector = (
        enable_collector_env.lower() in ("1", "true", "yes")
        if enable_collector_env is not None
        else (ENVIRONMENT != "test")
    )

    collector = None
    if should_run_collector:
        from app.services.kjpl.live_rate_service import get_city_live_collector
        collector = get_city_live_collector()
        await collector.start()

    try:
        yield
    finally:
        if collector:
            await collector.stop()


app = FastAPI(
    title="VMD Bullion Intelligence Terminal",
    description="Bloomberg-inspired Institutional Indian Bullion Intelligence Terminal (KJPL Exclusive)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-User-ID"],
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
def health_check(response: Response):
    db_health = check_database_health()
    is_ok = bool(db_health.get("connected"))
    if not is_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if is_ok else "degraded",
        "service": "VMD Bullion API",
        "version": "2.0.0",
        "database": db_health,
    }
