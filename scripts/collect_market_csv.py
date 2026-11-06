from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf


OUTPUT = Path("data/market/market_rates.csv")
IST = ZoneInfo("Asia/Kolkata")

SYMBOLS = {
    "USDINR": "USDINR=X",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
}


def get_latest_intraday_close(symbol: str) -> float:
    ticker = yf.Ticker(symbol)

    # Attempt 1: 2-day 15-minute intraday close with 3x retry
    for attempt in range(1, 4):
        try:
            history = ticker.history(period="2d", interval="15m")
            if not history.empty:
                closes = history["Close"].dropna()
                if not closes.empty:
                    return float(closes.iloc[-1])
        except Exception as e:
            if attempt == 3:
                print(f"[MARKET COLLECTOR] Intraday fetch error for {symbol} (attempt {attempt}/3): {e}")
            time.sleep(2)

    # Attempt 2: 5-day daily close fallback (crucial for weekends, market holidays, or exchange breaks)
    try:
        daily_history = ticker.history(period="5d", interval="1d")
        if not daily_history.empty:
            closes = daily_history["Close"].dropna()
            if not closes.empty:
                print(f"[MARKET COLLECTOR] Note: Using daily close fallback for {symbol}")
                return float(closes.iloc[-1])
    except Exception as e:
        print(f"[MARKET COLLECTOR] Daily fallback error for {symbol}: {e}")

    # Attempt 3: Read last-known-good price from CSV if upstream provider is unreachable
    if OUTPUT.exists():
        try:
            with OUTPUT.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                if rows:
                    last_row = rows[-1]
                    field_map = {"USDINR=X": "usdinr", "GC=F": "xauusd", "SI=F": "xagusd"}
                    col = field_map.get(symbol)
                    if col and col in last_row:
                        val = float(last_row[col])
                        print(f"[MARKET COLLECTOR] Warning: Using last known good value for {symbol}: {val}")
                        return val
        except Exception as csv_err:
            print(f"[MARKET COLLECTOR] CSV fallback read error: {csv_err}")

    raise RuntimeError(f"No valid price data returned for {symbol}")


def collect() -> None:
    observed_at = datetime.now(IST)

    values = {
        name: get_latest_intraday_close(symbol)
        for name, symbol in SYMBOLS.items()
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    file_exists = OUTPUT.exists()

    with OUTPUT.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "observed_at",
                "usdinr",
                "xauusd",
                "xagusd",
                "source",
            ],
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "observed_at": observed_at.isoformat(),
                "usdinr": values["USDINR"],
                "xauusd": values["XAUUSD"],
                "xagusd": values["XAGUSD"],
                "source": "Yahoo Finance",
            }
        )

    print(
        f"[MARKET CSV] {observed_at.isoformat()} "
        f"USDINR={values['USDINR']:.4f} "
        f"XAUUSD={values['XAUUSD']:.4f} "
        f"XAGUSD={values['XAGUSD']:.4f}"
    )


if __name__ == "__main__":
    collect()
