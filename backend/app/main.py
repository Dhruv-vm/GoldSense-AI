from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.kjpl import router as kjpl_router
from app.api.routes.market import router as market_router
from app.api.routes.prediction import router as prediction_router
from app.jobs.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="GoldSense AI",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(kjpl_router)
app.include_router(market_router)
app.include_router(prediction_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
