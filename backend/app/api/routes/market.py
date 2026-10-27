from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.market_rate import MarketRate
from app.services.data_service import (
    get_market_overview,
    get_latest_market_from_csv,
    refresh_market_data,
)

router = APIRouter(prefix="/api/market", tags=["Market"])


@router.get("/overview")
def market_overview():
    """
    Unified market overview including:
      - KJPL gold and silver benchmarks
      - US gold (GC=F) and silver (SI=F) futures
      - USD/INR forex spot
      - Converted international price in INR/g
      - Domestic bullion premium (INR and %)
      - 24h price movements and freshness labels
    """
    return get_market_overview()


@router.post("/refresh")
def trigger_market_refresh():
    """
    Trigger an active market refresh if cooldown period (60s) has passed.
    Preserves last-known-good values on failure.
    """
    return refresh_market_data()


@router.get("/latest")
def get_latest_market_rate():
    """
    Return the latest market rate. Falls back to CSV observation if SQL DB is unpopulated.
    """
    db = SessionLocal()
    try:
        result = db.execute(
            select(MarketRate)
            .order_by(MarketRate.observed_at.desc())
            .limit(1)
        )
        rate = result.scalar_one_or_none()

        if rate is not None:
            return {
                "id": rate.id,
                "symbol": rate.symbol,
                "value": rate.value,
                "currency": rate.currency,
                "unit": rate.unit,
                "observed_at": rate.observed_at.isoformat() if hasattr(rate.observed_at, "isoformat") else str(rate.observed_at),
                "source": rate.source,
            }
    except Exception:
        pass
    finally:
        db.close()

    # Fallback to canonical CSV
    csv_rate = get_latest_market_from_csv()
    if csv_rate:
        return {
            "id": 1,
            "symbol": "USDINR",
            "value": csv_rate["usdinr"],
            "currency": "INR",
            "unit": "USD",
            "observed_at": csv_rate["observed_at"],
            "source": csv_rate["source"],
            "xauusd": csv_rate["xauusd"],
            "xagusd": csv_rate["xagusd"],
            "freshness": csv_rate["freshness"],
        }

    raise HTTPException(status_code=404, detail="No market rate found")
