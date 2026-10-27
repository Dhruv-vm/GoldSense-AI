from __future__ import annotations

import csv
from pathlib import Path
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.gold_rate import GoldRate
from app.services.data_service import get_latest_kjpl_from_csv, KJPL_CSV

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

        if rate is not None:
            return {
                "id": rate.id,
                "source": rate.source,
                "gold_mjdta": rate.gold_mjdta,
                "gold_with_gst": rate.gold_with_gst,
                "silver_mjdta": rate.silver_mjdta,
                "source_updated_time": rate.source_updated_time,
                "observed_at": rate.observed_at.isoformat() if hasattr(rate.observed_at, "isoformat") else str(rate.observed_at),
                "currency": rate.currency,
                "unit": rate.unit,
            }
    except Exception:
        pass
    finally:
        db.close()

    # Fallback to canonical CSV
    csv_rate = get_latest_kjpl_from_csv()
    if csv_rate:
        return {
            "id": 1,
            "source": csv_rate["source"],
            "gold_mjdta": csv_rate["gold_mjdta"],
            "gold_with_gst": round(csv_rate["gold_mjdta"] * 1.03, 2),
            "silver_mjdta": csv_rate["silver_mjdta"],
            "source_updated_time": csv_rate["published_time"],
            "observed_at": csv_rate["observed_at"],
            "currency": csv_rate["currency"],
            "unit": csv_rate["unit"],
            "freshness": csv_rate["freshness"],
        }

    raise HTTPException(status_code=404, detail="No KJPL rate found")


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
        if rates:
            return [
                {
                    "id": rate.id,
                    "gold_mjdta": rate.gold_mjdta,
                    "gold_with_gst": rate.gold_with_gst,
                    "silver_mjdta": rate.silver_mjdta,
                    "source_updated_time": rate.source_updated_time,
                    "observed_at": rate.observed_at.isoformat() if hasattr(rate.observed_at, "isoformat") else str(rate.observed_at),
                    "currency": rate.currency,
                    "unit": rate.unit,
                }
                for rate in rates
            ]
    except Exception:
        pass
    finally:
        db.close()

    # Fallback to CSV history
    if KJPL_CSV.exists():
        with KJPL_CSV.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            rows = reader[-limit:]
            rows.reverse()
            return [
                {
                    "id": idx + 1,
                    "gold_mjdta": float(r["gold_mjdta"]),
                    "gold_with_gst": round(float(r["gold_mjdta"]) * 1.03, 2),
                    "silver_mjdta": float(r["silver_mjdta"]) if r.get("silver_mjdta") else 220.0,
                    "source_updated_time": r.get("published_time", "N/A"),
                    "observed_at": r["observed_at"],
                    "currency": "INR",
                    "unit": "gram",
                }
                for idx, r in enumerate(rows)
            ]

    return []
