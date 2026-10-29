from __future__ import annotations

import csv
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.gold_rate import GoldRate
from app.models.market_rate import MarketRate

IST = ZoneInfo("Asia/Kolkata")
TROY_OUNCE_GRAMS = 31.1034768
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

KJPL_CSV = PROJECT_ROOT / "data/kjpl/kjpl_rates.csv"
MARKET_CSV = PROJECT_ROOT / "data/market/market_rates.csv"
NEWS_CSV = PROJECT_ROOT / "data/news/news_articles.csv"
NEWS_ARCHIVE_CSV = PROJECT_ROOT / "data/news/news_articles.csv"
LIVE_NEWS_CSV = PROJECT_ROOT / "data/news/live_news.csv"
ANALYZED_NEWS_CSV = PROJECT_ROOT / "backend/ml/data/processed/analyzed_news.csv"

# Global rate limit for active market refreshes (minimum 60s cooldown)
LAST_REFRESH_TIME: float = 0.0
REFRESH_COOLDOWN_SECONDS: float = 60.0


def init_database() -> None:
    """Ensure database tables exist."""
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"[DATA SERVICE] Warning creating tables: {e}")


def get_market_trading_status() -> dict[str, Any]:
    """
    Evaluate trading session status for both domestic Indian spot bullion
    and international COMEX futures / global forex.
    """
    now_ist = datetime.now(IST)
    weekday = now_ist.weekday()  # Monday is 0, Sunday is 6
    hour = now_ist.hour
    minute = now_ist.minute

    # Indian Physical Market (KJPL / Ahmedabad spot)
    if weekday == 6:  # Sunday
        indian_status = "SUNDAY_CLOSED"
        indian_desc = "Physical bullion market is closed on Sundays."
    elif 10 <= hour < 19:
        indian_status = "OPEN"
        indian_desc = "Physical bullion market active (10:00 AM - 7:00 PM IST)."
    else:
        indian_status = "AFTER_HOURS"
        indian_desc = "Physical bullion market after-hours."

    # US COMEX / Global Forex Market
    # COMEX closed Saturday 02:30 IST to Monday 03:30 IST
    if (weekday == 5 and (hour > 2 or (hour == 2 and minute >= 30))) or weekday == 6 or (weekday == 0 and (hour < 3 or (hour == 3 and minute < 30))):
        global_status = "WEEKEND_CLOSED"
        global_desc = "COMEX & global forex closed for weekend."
    elif 3 <= hour < 4:
        global_status = "DAILY_SETTLEMENT_BREAK"
        global_desc = "CME daily maintenance & settlement pause."
    else:
        global_status = "OPEN"
        global_desc = "Global precious metals futures & forex active."

    return {
        "indian_physical_market": indian_status,
        "indian_physical_description": indian_desc,
        "global_futures_market": global_status,
        "global_futures_description": global_desc,
        "server_time_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
    }


def get_freshness_status(observed_at: datetime) -> str:
    """
    Evaluate honest data freshness based on elapsed time from observation:
      - FRESH:   < 4 hours
      - DELAYED: 4 - 24 hours
      - STALE:   > 24 hours
    """
    now_utc = datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        obs_utc = observed_at.replace(tzinfo=timezone.utc)
    else:
        obs_utc = observed_at.astimezone(timezone.utc)

    age_hours = (now_utc - obs_utc).total_seconds() / 3600.0
    if age_hours < 4.0:
        return "FRESH"
    elif age_hours < 24.0:
        return "DELAYED"
    else:
        return "STALE"


def get_latest_kjpl_from_csv() -> dict[str, Any] | None:
    """Read the latest KJPL record from canonical CSV."""
    if not KJPL_CSV.exists():
        return None

    with KJPL_CSV.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        if not reader:
            return None

        latest = reader[-1]
        prev = reader[-2] if len(reader) > 1 else None

        gold = float(latest["gold_mjdta"])
        silver = float(latest["silver_mjdta"]) if latest.get("silver_mjdta") else 220.0
        obs_time = datetime.fromisoformat(latest["observed_at"])
        pub_time = latest.get("published_time", "N/A")

        # 24h / previous change
        prev_gold = float(prev["gold_mjdta"]) if prev else gold
        change_inr = round(gold - prev_gold, 2)
        change_pct = round((change_inr / prev_gold) * 100, 2) if prev_gold > 0 else 0.0

        return {
            "source": "KJPL (MJDTA Benchmark)",
            "gold_mjdta": gold,
            "silver_mjdta": silver,
            "published_time": pub_time,
            "observed_at": obs_time.isoformat(),
            "currency": "INR",
            "unit": "gram",
            "change_24h_inr": change_inr,
            "change_24h_pct": change_pct,
            "freshness": get_freshness_status(obs_time),
        }


def get_latest_market_from_csv() -> dict[str, Any] | None:
    """Read the latest US market observation from canonical CSV."""
    if not MARKET_CSV.exists():
        return None

    with MARKET_CSV.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        if not reader:
            return None

        latest = reader[-1]
        prev = reader[-2] if len(reader) > 1 else None

        xau = float(latest["xauusd"])
        xag = float(latest["xagusd"])
        usdinr = float(latest["usdinr"])
        obs_time = datetime.fromisoformat(latest["observed_at"])

        prev_xau = float(prev["xauusd"]) if prev else xau
        prev_usdinr = float(prev["usdinr"]) if prev else usdinr

        xau_change = round(xau - prev_xau, 2)
        xau_pct = round((xau_change / prev_xau) * 100, 2) if prev_xau > 0 else 0.0
        usdinr_change = round(usdinr - prev_usdinr, 4)

        return {
            "xauusd": xau,
            "xagusd": xag,
            "usdinr": usdinr,
            "observed_at": obs_time.isoformat(),
            "source": "Yahoo Finance (COMEX & Forex)",
            "xauusd_change_24h": xau_change,
            "xauusd_change_24h_pct": xau_pct,
            "usdinr_change_24h": usdinr_change,
            "freshness": get_freshness_status(obs_time),
        }


def get_market_overview() -> dict[str, Any]:
    """
    Unified real-time market overview combining domestic Indian bullion and
    international futures, computing exact conversion and premiums.
    """
    kjpl = get_latest_kjpl_from_csv()
    market = get_latest_market_from_csv()

    if not kjpl or not market:
        return {
            "status": "ERROR",
            "message": "Market data files are not accessible or empty.",
        }

    xau = market["xauusd"]
    usdinr = market["usdinr"]
    xag = market["xagusd"]
    kjpl_gold = kjpl["gold_mjdta"]
    kjpl_silver = kjpl["silver_mjdta"]

    # Converted international gold rate in INR per gram:
    # (XAUUSD * USDINR) / 31.1034768
    global_gold_inr_per_gram = round((xau * usdinr) / TROY_OUNCE_GRAMS, 2)
    global_silver_inr_per_gram = round((xag * usdinr) / TROY_OUNCE_GRAMS, 2)

    # Domestic premium (KJPL vs International converted price)
    domestic_premium_inr = round(kjpl_gold - global_gold_inr_per_gram, 2)
    domestic_premium_pct = round((domestic_premium_inr / global_gold_inr_per_gram) * 100, 2)

    # Gold / Silver ratios
    global_gold_silver_ratio = round(xau / xag, 2) if xag > 0 else 0.0
    domestic_gold_silver_ratio = round(kjpl_gold / kjpl_silver, 2) if kjpl_silver > 0 else 0.0

    return {
        "status": "SUCCESS",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kjpl": kjpl,
        "market": market,
        "derived": {
            "global_gold_inr_per_gram": global_gold_inr_per_gram,
            "global_silver_inr_per_gram": global_silver_inr_per_gram,
            "domestic_premium_inr_per_gram": domestic_premium_inr,
            "domestic_premium_pct": domestic_premium_pct,
            "global_gold_silver_ratio": global_gold_silver_ratio,
            "domestic_gold_silver_ratio": domestic_gold_silver_ratio,
            "conversion_factor": TROY_OUNCE_GRAMS,
        },
        "overall_freshness": "FRESH" if kjpl["freshness"] == "FRESH" and market["freshness"] == "FRESH" else "DELAYED",
        "trading_status": get_market_trading_status(),
    }


def refresh_market_data() -> dict[str, Any]:
    """
    Attempt an active market refresh if cooldown period has passed.
    Never overwrites data or creates duplicates.
    """
    global LAST_REFRESH_TIME
    now = time.time()
    elapsed = now - LAST_REFRESH_TIME

    if elapsed < REFRESH_COOLDOWN_SECONDS:
        remaining = int(REFRESH_COOLDOWN_SECONDS - elapsed)
        overview = get_market_overview()
        overview["message"] = f"Refresh rate limited. Retaining latest observations (cooldown: {remaining}s remaining)."
        overview["refreshed"] = False
        return overview

    # Attempt fetch
    try:
        import yfinance as yf
        tickers = {
            "USDINR": "USDINR=X",
            "XAUUSD": "GC=F",
            "XAGUSD": "SI=F",
        }
        latest_vals = {}
        for name, sym in tickers.items():
            t = yf.Ticker(sym)
            hist = t.history(period="1d", interval="15m")
            if not hist.empty:
                latest_vals[name] = float(hist["Close"].dropna().iloc[-1])

        if len(latest_vals) == 3:
            obs_at = datetime.now(IST)
            # Append only if values differ or significant time elapsed (> 30 min)
            market_curr = get_latest_market_from_csv()
            should_append = True
            if market_curr:
                last_time = datetime.fromisoformat(market_curr["observed_at"])
                if (datetime.now(timezone.utc) - last_time.astimezone(timezone.utc)).total_seconds() < 1800:
                    if (
                        market_curr["xauusd"] == latest_vals["XAUUSD"]
                        and market_curr["usdinr"] == latest_vals["USDINR"]
                    ):
                        should_append = False

            if should_append:
                MARKET_CSV.parent.mkdir(parents=True, exist_ok=True)
                with MARKET_CSV.open("a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=["observed_at", "usdinr", "xauusd", "xagusd", "source"])
                    w.writerow({
                        "observed_at": obs_at.isoformat(),
                        "usdinr": latest_vals["USDINR"],
                        "xauusd": latest_vals["XAUUSD"],
                        "xagusd": latest_vals["XAGUSD"],
                        "source": "Yahoo Finance",
                    })

        LAST_REFRESH_TIME = now
        overview = get_market_overview()
        overview["message"] = "Market data successfully refreshed."
        overview["refreshed"] = True
        return overview

    except Exception as e:
        overview = get_market_overview()
        overview["message"] = f"Refresh attempt encountered provider error: {str(e)}. Retaining last-known-good observation."
        overview["refreshed"] = False
        return overview
