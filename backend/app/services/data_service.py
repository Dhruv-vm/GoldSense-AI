from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any
from sqlalchemy import select, desc

from app.db.base import Base
from app.db.session import engine, SessionLocal, ENVIRONMENT, check_database_health
from app.models.bullion import BullionLatestRate, BullionRateObservation, DataSourceStatus

IST = ZoneInfo("Asia/Kolkata")
TROY_OUNCE_GRAMS = 31.1034768
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

KJPL_CSV = PROJECT_ROOT / "data/kjpl/kjpl_rates.csv"
NEWS_CSV = PROJECT_ROOT / "data/news/news_articles.csv"
NEWS_ARCHIVE_CSV = PROJECT_ROOT / "data/news/news_articles.csv"
LIVE_NEWS_CSV = PROJECT_ROOT / "data/news/live_news.csv"
ANALYZED_NEWS_CSV = PROJECT_ROOT / "backend/ml/data/processed/analyzed_news.csv"

# Freshness thresholds (configurable in hours/seconds by feed type)
MJDTA_FRESH_HOURS = float(os.environ.get("MJDTA_FRESH_HOURS", "16.0"))   # Twice-daily benchmark
MJDTA_DELAYED_HOURS = float(os.environ.get("MJDTA_DELAYED_HOURS", "36.0"))
LIVE_FEED_LIVE_SECONDS = float(os.environ.get("KJPL_LIVE_SECONDS", "120.0"))
LIVE_FEED_FRESH_HOURS = float(os.environ.get("KJPL_LIVE_FRESH_HOURS", "4.0"))
LIVE_FEED_DELAYED_HOURS = float(os.environ.get("KJPL_LIVE_DELAYED_HOURS", "24.0"))


def init_database() -> None:
    """Create database tables in local development/test mode only; production relies on Alembic migrations."""
    if ENVIRONMENT == "production":
        return
    try:
        import app.models  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"[DATA SERVICE] Warning creating local tables: {e}")


def get_market_trading_status() -> dict[str, Any]:
    """
    Evaluate trading session status for Indian physical bullion & KJPL terminal hours.
    Does not fabricate international external feed statuses; tracks KJPL market schedule.
    """
    now_ist = datetime.now(IST)
    weekday = now_ist.weekday()  # Monday=0 .. Sunday=6
    hour = now_ist.hour
    minute = now_ist.minute

    if weekday == 6:  # Sunday
        indian_status = "SUNDAY_CLOSED"
        indian_desc = "Indian physical bullion market and KJPL desk are closed on Sundays."
    elif 9 <= hour < 23 or (hour == 23 and minute <= 30):
        # Active MJDTA + MCX-linked KJPL live bullion desk window (09:00 AM - 11:30 PM IST Mon-Fri, 09:00 AM - 07:00 PM Sat)
        if weekday == 5 and hour >= 19:
            indian_status = "AFTER_HOURS"
            indian_desc = "Saturday physical bullion trading hours concluded."
        else:
            indian_status = "OPEN"
            indian_desc = "Indian physical bullion market & KJPL desk active."
    else:
        indian_status = "AFTER_HOURS"
        indian_desc = "KJPL physical bullion market after-hours."

    # Keep global_futures_market key for backward schema compatibility, derived strictly from schedule/KJPL hours
    if weekday == 6 or (weekday == 5 and hour >= 19):
        global_status = "WEEKEND_CLOSED"
        global_desc = "KJPL international reference desk closed for weekend."
    elif hour == 3:
        global_status = "DAILY_SETTLEMENT_BREAK"
        global_desc = "Daily international bullion settlement pause."
    else:
        global_status = "OPEN"
        global_desc = "KJPL international bullion reference feeds active."

    return {
        "indian_physical_market": indian_status,
        "indian_physical_description": indian_desc,
        "global_futures_market": global_status,
        "global_futures_description": global_desc,
        "server_time_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
    }


def _format_age_display(age_seconds: float) -> str:
    if age_seconds < 60:
        return f"{int(age_seconds)}s ago"
    if age_seconds < 3600:
        return f"{int(age_seconds / 60)}m ago"
    if age_seconds < 86400:
        hours = int(age_seconds / 3600)
        mins = int((age_seconds % 3600) / 60)
        return f"{hours}h {mins}m ago" if mins > 0 else f"{hours}h ago"
    days = int(age_seconds / 86400)
    hours = int((age_seconds % 86400) / 3600)
    return f"{days}d {hours}h ago"


def get_freshness_details(
    reference_dt: datetime | None,
    *,
    rate_type: str = "RETAIL",
    market_status_override: str | None = None,
    source_unavailable: bool = False,
) -> dict[str, Any]:
    """
    Evaluate honest freshness state tailored to feed cadence:
      - MJDTA_BENCHMARK (twice daily): FRESH <16h, DELAYED 16-36h, STALE >36h
      - Live feeds (KJPL_LIVE / RETAIL / WHOLESALE): LIVE <120s, FRESH <4h, DELAYED 4-24h, STALE >24h
    Respects market-closed and source-unavailable states without fabricating activity.
    """
    if source_unavailable:
        return {
            "status": "SOURCE_UNAVAILABLE",
            "age_hours": None,
            "age_seconds": None,
            "age_display": "Source unavailable",
        }
    if reference_dt is None:
        return {
            "status": "STALE",
            "age_hours": None,
            "age_seconds": None,
            "age_display": "Unknown timestamp",
        }

    now_utc = datetime.now(timezone.utc)
    obs_utc = reference_dt.replace(tzinfo=timezone.utc) if reference_dt.tzinfo is None else reference_dt.astimezone(timezone.utc)
    age_seconds = max(0.0, (now_utc - obs_utc).total_seconds())
    age_hours = round(age_seconds / 3600.0, 2)
    age_display = _format_age_display(age_seconds)

    if market_status_override in ("SUNDAY_CLOSED", "WEEKEND_CLOSED", "CLOSED"):
        status = "MARKET_CLOSED"
    elif rate_type in ("MJDTA_BENCHMARK", "LBMA_FIX"):
        if age_hours < MJDTA_FRESH_HOURS:
            status = "FRESH"
        elif age_hours < MJDTA_DELAYED_HOURS:
            status = "DELAYED"
        else:
            status = "STALE"
    else:
        if age_seconds <= LIVE_FEED_LIVE_SECONDS:
            status = "LIVE"
        elif age_hours < LIVE_FEED_FRESH_HOURS:
            status = "FRESH"
        elif age_hours < LIVE_FEED_DELAYED_HOURS:
            status = "DELAYED"
        else:
            status = "STALE"

    return {
        "status": status,
        "age_hours": age_hours,
        "age_seconds": round(age_seconds, 1),
        "age_display": age_display,
    }


def get_freshness_status(observed_at: datetime) -> str:
    return get_freshness_details(observed_at)["status"]


def _get_latest_kjpl_from_db() -> dict[str, Any] | None:
    """Query MJDTA Gold & Silver strictly from validated BullionLatestRate / BullionRateObservation."""
    db = SessionLocal()
    try:
        gold_row = db.execute(
            select(BullionLatestRate).where(
                BullionLatestRate.city_code == "CHENNAI",
                BullionLatestRate.product_id == "MJDTA_GOLD_24K",
                BullionLatestRate.validation_status.in_(["VALID", "SUSPECT"]),
            )
        ).scalar_one_or_none()
        if gold_row is None:
            return None

        silver_row = db.execute(
            select(BullionLatestRate).where(
                BullionLatestRate.city_code == "CHENNAI",
                BullionLatestRate.product_id == "MJDTA_SILVER",
                BullionLatestRate.validation_status.in_(["VALID", "SUSPECT"]),
            )
        ).scalar_one_or_none()

        gold = float(gold_row.latest_price)
        prev_gold = float(gold_row.previous_price) if gold_row.previous_price is not None else gold
        silver = float(silver_row.latest_price) if silver_row is not None else None
        change_inr = float(gold_row.change_inr)
        change_pct = float(gold_row.change_pct)

        pub_dt = gold_row.source_published_at
        coll_dt = gold_row.last_collected_at
        freshness = get_freshness_details(pub_dt or coll_dt, rate_type="MJDTA_BENCHMARK")

        return {
            "source": "KJPL (MJDTA Benchmark)",
            "gold_mjdta": gold,
            "silver_mjdta": silver,
            "published_time": pub_dt.astimezone(IST).strftime("%d-%m-%Y %I:%M %p IST") if pub_dt else "Unverified date",
            "source_published_at": pub_dt.isoformat() if pub_dt else None,
            "observed_at": coll_dt.isoformat(),
            "last_verified_at": gold_row.last_verified_at.isoformat(),
            "currency": "INR",
            "unit": "gram",
            "change_24h_inr": round(change_inr, 2),
            "change_24h_pct": round(change_pct, 2),
            "freshness": freshness["status"],
            "age_hours": freshness["age_hours"],
            "age_display": freshness["age_display"],
        }
    finally:
        db.close()


def get_latest_kjpl_from_csv() -> dict[str, Any] | None:
    """
    Retrieve latest validated KJPL MJDTA record.
    Reads from database first; CSV fallback is strictly prohibited in production.
    """
    try:
        db_val = _get_latest_kjpl_from_db()
        if db_val is not None:
            return db_val
    except Exception:
        if ENVIRONMENT == "production":
            return None

    if ENVIRONMENT == "production" or not KJPL_CSV.exists():
        return None

    with KJPL_CSV.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        if not reader:
            return None

        latest = reader[-1]
        prev = reader[-2] if len(reader) > 1 else None
        gold = float(latest["gold_mjdta"])
        silver = float(latest["silver_mjdta"]) if latest.get("silver_mjdta") else None
        obs_time = datetime.fromisoformat(latest["observed_at"])
        pub_time = latest.get("published_time", "N/A")

        prev_gold = float(prev["gold_mjdta"]) if prev else gold
        change_inr = round(gold - prev_gold, 2)
        change_pct = round((change_inr / prev_gold) * 100, 2) if prev_gold > 0 else 0.0
        kjpl_freshness = get_freshness_details(obs_time, rate_type="MJDTA_BENCHMARK")

        return {
            "source": "KJPL (MJDTA Benchmark)",
            "gold_mjdta": gold,
            "silver_mjdta": silver,
            "published_time": pub_time,
            "source_published_at": None,
            "observed_at": obs_time.isoformat(),
            "last_verified_at": obs_time.isoformat(),
            "currency": "INR",
            "unit": "gram",
            "change_24h_inr": change_inr,
            "change_24h_pct": change_pct,
            "freshness": kjpl_freshness["status"],
            "age_hours": kjpl_freshness["age_hours"],
            "age_display": kjpl_freshness["age_display"],
        }


def get_latest_market_from_csv() -> dict[str, Any] | None:
    """
    Retrieve international spot & FX reference strictly from KJPL Live Type 1 feeds
    (`KJPL_SPOT_GOLD_USD`, `KJPL_SPOT_SILVER_USD`, `KJPL_SPOT_USDINR`) stored in DB.
    Yahoo Finance and external APIs are permanently disabled per the KJPL-only rule.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(BullionLatestRate).where(
                BullionLatestRate.product_id.in_([
                    "KJPL_SPOT_GOLD_USD",
                    "KJPL_SPOT_SILVER_USD",
                    "KJPL_SPOT_USDINR",
                ]),
                BullionLatestRate.validation_status.in_(["VALID", "SUSPECT"]),
            )
        ).scalars().all()
        by_pid = {r.product_id: r for r in rows}
        gold_r = by_pid.get("KJPL_SPOT_GOLD_USD")
        silver_r = by_pid.get("KJPL_SPOT_SILVER_USD")
        fx_r = by_pid.get("KJPL_SPOT_USDINR")
        if not (gold_r and silver_r and fx_r):
            return None

        freshness = get_freshness_details(
            gold_r.source_published_at or gold_r.last_verified_at,
            rate_type="KJPL_LIVE",
        )
        return {
            "xauusd": float(gold_r.latest_price),
            "xagusd": float(silver_r.latest_price),
            "usdinr": float(fx_r.latest_price),
            "observed_at": gold_r.last_collected_at.isoformat(),
            "source_published_at": gold_r.source_published_at.isoformat() if gold_r.source_published_at else None,
            "source": "KJPL Live Feed (SPOT-GOLD / SPOT-SILVER / SPOT-INR)",
            "xauusd_change_24h": float(gold_r.change_inr),
            "xauusd_change_24h_pct": float(gold_r.change_pct),
            "usdinr_change_24h": float(fx_r.change_inr),
            "freshness": freshness["status"],
            "age_hours": freshness["age_hours"],
            "age_display": freshness["age_display"],
        }
    except Exception:
        return None
    finally:
        db.close()


def get_market_overview() -> dict[str, Any]:
    """
    Consolidated market overview sourced strictly from KJPL data in database.
    Reports explicit unavailable/degraded state when DB or KJPL feeds are absent.
    """
    db_health = check_database_health()
    if not db_health.get("connected"):
        return {
            "status": "DEGRADED",
            "message": "Database unavailable. Cannot serve verified live bullion overview.",
            "database": db_health,
        }

    kjpl = get_latest_kjpl_from_csv()
    market = get_latest_market_from_csv()

    if not kjpl:
        return {
            "status": "UNAVAILABLE",
            "message": "Verified KJPL MJDTA rates are not yet populated in the database.",
            "trading_status": get_market_trading_status(),
        }

    derived: dict[str, Any] = {
        "conversion_factor": TROY_OUNCE_GRAMS,
        "domestic_gold_silver_ratio": (
            round(kjpl["gold_mjdta"] / kjpl["silver_mjdta"], 2)
            if kjpl.get("silver_mjdta") and kjpl["silver_mjdta"] > 0
            else None
        ),
    }

    if market:
        xau = market["xauusd"]
        usdinr = market["usdinr"]
        xag = market["xagusd"]
        global_gold_inr = round((xau * usdinr) / TROY_OUNCE_GRAMS, 2)
        global_silver_inr = round((xag * usdinr) / TROY_OUNCE_GRAMS, 2)
        premium_inr = round(kjpl["gold_mjdta"] - global_gold_inr, 2)
        premium_pct = round((premium_inr / global_gold_inr) * 100, 2) if global_gold_inr > 0 else None
        derived.update({
            "global_gold_inr_per_gram": global_gold_inr,
            "global_silver_inr_per_gram": global_silver_inr,
            "domestic_premium_inr_per_gram": premium_inr,
            "domestic_premium_pct": premium_pct,
            "global_gold_silver_ratio": round(xau / xag, 2) if xag > 0 else None,
        })
        if kjpl["freshness"] == "STALE" or market["freshness"] == "STALE":
            overall_freshness = "STALE"
        elif kjpl["freshness"] == "DELAYED" or market["freshness"] == "DELAYED":
            overall_freshness = "DELAYED"
        else:
            overall_freshness = "FRESH"
    else:
        overall_freshness = kjpl["freshness"]

    return {
        "status": "SUCCESS",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kjpl": kjpl,
        "market": market,
        "derived": derived,
        "overall_freshness": overall_freshness,
        "trading_status": get_market_trading_status(),
    }


def refresh_market_data() -> dict[str, Any]:
    """
    Manual refresh endpoint stub: returns latest verified KJPL database snapshot.
    External Yahoo Finance scraping is prohibited; dedicated Oracle/GitHub workers write KJPL feeds.
    """
    overview = get_market_overview()
    overview["refreshed"] = False
    overview["message"] = (
        "VMD Bullion runs dedicated KJPL-only collectors (single-writer model). "
        "Returning latest verified KJPL observations from database."
    )
    return overview
