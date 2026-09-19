from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.models.feature_snapshot import FeatureSnapshot
from app.models.gold_rate import GoldRate
from app.models.market_rate import MarketRate


def collect_feature_snapshot() -> FeatureSnapshot:
    db = SessionLocal()

    try:
        gold = (
            db.query(GoldRate)
            .order_by(GoldRate.observed_at.desc())
            .first()
        )

        if gold is None:
            raise RuntimeError("No KJPL gold rate available")

        market_rates = (
            db.query(MarketRate)
            .order_by(MarketRate.observed_at.desc())
            .all()
        )

        latest = {}

        for rate in market_rates:
            if rate.symbol not in latest:
                latest[rate.symbol] = rate

        required_symbols = {"USDINR", "XAUUSD", "XAGUSD"}

        missing = required_symbols - latest.keys()

        if missing:
            raise RuntimeError(
                f"Missing market rates: {', '.join(sorted(missing))}"
            )

        snapshot_time = datetime.now(ZoneInfo("Asia/Kolkata"))

        snapshot = FeatureSnapshot(
            observed_at=snapshot_time,
            kjpl_gold=gold.gold_mjdta,
            usdinr=latest["USDINR"].value,
            xauusd=latest["XAUUSD"].value,
            xagusd=latest["XAGUSD"].value,
        )

        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        return snapshot

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()