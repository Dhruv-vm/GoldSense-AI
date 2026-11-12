from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import app.db.session as db_session
from app.db.session import get_db
from app.models.bullion import BullionLatestRate
from app.services.bullion_service import (
    get_all_cities,
    get_latest_city_rates,
    get_city_comparison,
    get_bullion_summary,
    get_bullion_history,
    get_bullion_dashboard,
    normalize_city_code,
)

router = APIRouter(prefix="/api/bullion", tags=["Bullion Intelligence"])


@router.get("/dashboard")
def get_consolidated_dashboard(
    city: str = Query("CHENNAI", description="City code for initial historical observation trace"),
    history_limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Consolidated dashboard payload returning summary, cities, latest rates,
    city comparison matrix, data monitor status, and city history in 1 request.
    """
    norm_city = normalize_city_code(city)
    return get_bullion_dashboard(city_code=norm_city, history_limit=history_limit, db=db)


@router.get("/latest")
def get_bullion_latest(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_bullion_summary(db=db)


@router.get("/cities")
def get_bullion_cities(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return get_all_cities(db=db)


@router.get("/city-rates")
def get_bullion_city_rates(
    city: str | None = Query(None, description="Optional city code filter (e.g. chennai, bengaluru, mumbai)"),
    metal: str | None = Query(None, description="Optional metal filter (GOLD, SILVER, FX)"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return get_latest_city_rates(city_code=city, metal=metal, db=db)


@router.get("/city-rates/{city}")
def get_single_city_rates(
    city: str,
    metal: str | None = Query(None, description="Optional metal filter (GOLD or SILVER)"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    norm_city = normalize_city_code(city)
    rates = get_latest_city_rates(city_code=norm_city, metal=metal, db=db)
    if not rates:
        raise HTTPException(status_code=404, detail=f"No bullion rates found for city '{city}'")
    return rates


@router.get("/comparison")
def get_bullion_city_comparison(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_city_comparison(db=db)


@router.get("/history")
def get_bullion_observations_history(
    city: str | None = Query(None, description="City code (e.g. CHENNAI, BENGALURU)"),
    product_id: str | None = Query(None, description="Product ID (e.g. GOLD_100G_999, MJDTA_GOLD_24K)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    include_quarantined: bool = Query(False, description="Include quarantined rows for auditing"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return get_bullion_history(
        city_code=city,
        product_id=product_id,
        limit=limit,
        offset=offset,
        include_quarantined=include_quarantined,
        db=db,
    )


async def _bullion_sse_generator(request: Request) -> AsyncIterator[str]:
    """
    Stream genuine database state changes over SSE without manufacturing synthetic ticks.
    Emits 'snapshot' only when latest_price/last_collected_at advances, plus periodic 'heartbeat'.
    """
    last_watermark: str | None = None
    last_heartbeat = datetime.now(timezone.utc)

    while not await request.is_disconnected():
        try:
            with db_session.SessionLocal() as db:
                max_collected = db.execute(select(func.max(BullionLatestRate.last_collected_at))).scalar_one_or_none()
                max_verified = db.execute(select(func.max(BullionLatestRate.last_verified_at))).scalar_one_or_none()
                wm = f"{max_collected.isoformat() if max_collected else 'none'}|{max_verified.isoformat() if max_verified else 'none'}"
                if wm != last_watermark:
                    payload = get_bullion_dashboard(db=db)
                    last_watermark = wm
                    yield f"event: snapshot\ndata: {json.dumps(payload)}\n\n"
        except Exception as exc:
            yield f"event: status\ndata: {json.dumps({'status': 'DEGRADED', 'error': str(exc)})}\n\n"

        now = datetime.now(timezone.utc)
        if (now - last_heartbeat).total_seconds() >= 15:
            last_heartbeat = now
            yield f"event: heartbeat\ndata: {json.dumps({'ts': now.isoformat()})}\n\n"

        await asyncio.sleep(3.0)


@router.get("/stream")
async def stream_bullion_updates(request: Request):
    """Real-time SSE stream emitting genuine KJPL snapshot changes from PostgreSQL."""
    return StreamingResponse(
        _bullion_sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
