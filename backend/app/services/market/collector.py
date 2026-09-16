from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.models.market_rate import MarketRate
from .client import MarketClient


def collect_usdinr_rate() -> MarketRate:
    client = MarketClient()
    value = client.get_usdinr()

    db = SessionLocal()

    try:
        record = MarketRate(
            symbol="USDINR",
            value=value,
            currency="INR",
            unit="per USD",
            observed_at=datetime.now(ZoneInfo("Asia/Kolkata")),
            source="Yahoo Finance",
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