from app.db.session import SessionLocal
from app.models.gold_rate import GoldRate

from .client import KJPLClient


def collect_kjpl_rate() -> GoldRate:
    client = KJPLClient()
    rates = client.fetch_rates()

    db = SessionLocal()

    try:
        record = GoldRate(
            source=rates.source,
            gold_mjdta=rates.gold_mjdta,
            gold_with_gst=rates.gold_with_gst,
            silver_mjdta=rates.silver_mjdta,
            source_updated_time=rates.source_updated_time,
            observed_at=rates.observed_at,
            currency=rates.currency,
            unit=rates.unit,
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return record

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
