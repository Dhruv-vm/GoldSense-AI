from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.market_rate import MarketRate

router = APIRouter(prefix="/api/market", tags=["Market"])


@router.get("/latest")
def get_latest_market_rate():
    db = SessionLocal()

    try:
        result = db.execute(
            select(MarketRate)
            .where(MarketRate.symbol == "USDINR")
            .order_by(MarketRate.observed_at.desc())
            .limit(1)
        )

        rate = result.scalar_one_or_none()

        if rate is None:
            raise HTTPException(
                status_code=404,
                detail="No USD/INR market rate found",
            )

        return {
            "id": rate.id,
            "symbol": rate.symbol,
            "value": rate.value,
            "currency": rate.currency,
            "unit": rate.unit,
            "observed_at": rate.observed_at,
            "source": rate.source,
        }

    finally:
        db.close()


@router.get("/history")
def get_market_history(limit: int = 100):
    db = SessionLocal()

    try:
        result = db.execute(
            select(MarketRate)
            .where(MarketRate.symbol == "USDINR")
            .order_by(MarketRate.observed_at.desc())
            .limit(min(limit, 500))
        )

        rates = result.scalars().all()

        return [
            {
                "id": rate.id,
                "symbol": rate.symbol,
                "value": rate.value,
                "currency": rate.currency,
                "unit": rate.unit,
                "observed_at": rate.observed_at,
                "source": rate.source,
            }
            for rate in rates
        ]

    finally:
        db.close()