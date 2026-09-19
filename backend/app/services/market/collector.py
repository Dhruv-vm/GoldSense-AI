from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.models.market_rate import MarketRate
from .client import MarketClient


def _save_market_rate(
    symbol: str,
    value: float,
    currency: str,
    unit: str,
) -> MarketRate:
    db = SessionLocal()

    try:
        record = MarketRate(
            symbol=symbol,
            value=value,
            currency=currency,
            unit=unit,
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


def collect_usdinr_rate() -> MarketRate:
    client = MarketClient()

    return _save_market_rate(
        symbol="USDINR",
        value=client.get_usdinr(),
        currency="INR",
        unit="per USD",
    )


def collect_gold_usd_rate() -> MarketRate:
    client = MarketClient()

    return _save_market_rate(
        symbol="XAUUSD",
        value=client.get_gold_usd(),
        currency="USD",
        unit="per troy ounce",
    )
def collect_silver_usd_rate() -> MarketRate:
    client = MarketClient()

    return _save_market_rate(
        symbol="XAGUSD",
        value=client.get_silver_usd(),
        currency="USD",
        unit="per troy ounce",
    )