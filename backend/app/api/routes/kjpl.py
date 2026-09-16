from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.gold_rate import GoldRate

router = APIRouter(prefix="/api/kjpl", tags=["KJPL"])


@router.get("/latest")
def get_latest_kjpl_rate():
    db = SessionLocal()

    try:
        result = db.execute(
            select(GoldRate)
            .order_by(GoldRate.observed_at.desc())
            .limit(1)
        )

        rate = result.scalar_one_or_none()

        if rate is None:
            raise HTTPException(
                status_code=404,
                detail="No KJPL rate found",
            )

        return {
            "id": rate.id,
            "source": rate.source,
            "gold_mjdta": rate.gold_mjdta,
            "gold_with_gst": rate.gold_with_gst,
            "silver_mjdta": rate.silver_mjdta,
            "source_updated_time": rate.source_updated_time,
            "observed_at": rate.observed_at,
            "currency": rate.currency,
            "unit": rate.unit,
        }

    finally:
        db.close()


@router.get("/history")
def get_kjpl_history(limit: int = 100):
    db = SessionLocal()

    try:
        result = db.execute(
            select(GoldRate)
            .order_by(GoldRate.observed_at.desc())
            .limit(min(limit, 500))
        )

        rates = result.scalars().all()

        return [
            {
                "id": rate.id,
                "gold_mjdta": rate.gold_mjdta,
                "gold_with_gst": rate.gold_with_gst,
                "silver_mjdta": rate.silver_mjdta,
                "source_updated_time": rate.source_updated_time,
                "observed_at": rate.observed_at,
                "currency": rate.currency,
                "unit": rate.unit,
            }
            for rate in rates
        ]

    finally:
        db.close()
