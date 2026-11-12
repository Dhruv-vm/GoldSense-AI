from __future__ import annotations

import csv
from pathlib import Path
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, desc

import app.db.session as db_session
from app.db.session import ENVIRONMENT
from app.models.bullion import BullionRateObservation
from app.models.gold_rate import GoldRate
from app.services.data_service import get_latest_kjpl_from_csv, KJPL_CSV

router = APIRouter(prefix="/api/kjpl", tags=["KJPL"])


@router.get("/latest")
def get_latest_kjpl_rate():
    db = db_session.SessionLocal()
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
                "gold_mjdta": float(rate.gold_mjdta),
                "gold_with_gst": float(rate.gold_with_gst) if rate.gold_with_gst is not None else None,
                "silver_mjdta": float(rate.silver_mjdta) if rate.silver_mjdta is not None else None,
                "source_updated_time": rate.source_updated_time,
                "observed_at": rate.observed_at.isoformat() if hasattr(rate.observed_at, "isoformat") else str(rate.observed_at),
                "currency": rate.currency,
                "unit": rate.unit,
            }
    except Exception:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Database unavailable for KJPL latest rate")
    finally:
        db.close()

    # Read from validated BullionLatestRate or dev-only CSV (disabled in production)
    kjpl_data = get_latest_kjpl_from_csv()
    if kjpl_data:
        return {
            "id": 1,
            "source": kjpl_data["source"],
            "gold_mjdta": kjpl_data["gold_mjdta"],
            "gold_with_gst": round(kjpl_data["gold_mjdta"] * 1.03, 2) if kjpl_data.get("gold_mjdta") else None,
            "silver_mjdta": kjpl_data.get("silver_mjdta"),
            "source_updated_time": kjpl_data["published_time"],
            "observed_at": kjpl_data["observed_at"],
            "currency": kjpl_data["currency"],
            "unit": kjpl_data["unit"],
            "freshness": kjpl_data["freshness"],
        }

    raise HTTPException(status_code=404, detail="No KJPL rate found")


@router.get("/history")
def get_kjpl_history(limit: int = 100):
    db = db_session.SessionLocal()
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
                    "gold_mjdta": float(rate.gold_mjdta),
                    "gold_with_gst": float(rate.gold_with_gst) if rate.gold_with_gst is not None else None,
                    "silver_mjdta": float(rate.silver_mjdta) if rate.silver_mjdta is not None else None,
                    "source_updated_time": rate.source_updated_time,
                    "observed_at": rate.observed_at.isoformat() if hasattr(rate.observed_at, "isoformat") else str(rate.observed_at),
                    "currency": rate.currency,
                    "unit": rate.unit,
                }
                for rate in rates
            ]

        # Query validated BullionRateObservation MJDTA Gold history if legacy GoldRate table is empty
        obs_rows = db.execute(
            select(BullionRateObservation)
            .where(
                BullionRateObservation.city_code == "CHENNAI",
                BullionRateObservation.product_id == "MJDTA_GOLD_24K",
                BullionRateObservation.validation_status.in_(["VALID", "SUSPECT"]),
            )
            .order_by(desc(BullionRateObservation.observed_at))
            .limit(min(limit, 500))
        ).scalars().all()
        if obs_rows:
            return [
                {
                    "id": obs.id,
                    "gold_mjdta": float(obs.price),
                    "gold_with_gst": None,
                    "silver_mjdta": None,
                    "source_updated_time": (
                        obs.source_published_at.isoformat() if obs.source_published_at else None
                    ),
                    "observed_at": obs.observed_at.isoformat(),
                    "currency": obs.currency,
                    "unit": obs.unit,
                }
                for obs in obs_rows
            ]
    except Exception:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Database unavailable for KJPL history")
    finally:
        db.close()

    # Local dev CSV fallback strictly disabled in production; never fabricates missing silver (no 220.0 fallback)
    if ENVIRONMENT == "production":
        return []

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
                    "silver_mjdta": float(r["silver_mjdta"]) if r.get("silver_mjdta") else None,
                    "source_updated_time": r.get("published_time") or None,
                    "observed_at": r["observed_at"],
                    "currency": "INR",
                    "unit": "1g",
                }
                for idx, r in enumerate(rows)
            ]

    return []
