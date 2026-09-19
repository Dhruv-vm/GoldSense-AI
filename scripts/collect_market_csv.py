from __future__ import annotations

import csv
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


def get_latest_close(symbol: str) -> float:
    ticker = yf.Ticker(symbol)

    history = ticker.history(period="5d")

    if history.empty:
        raise RuntimeError(f"No market data returned for {symbol}")

    closes = history["Close"].dropna()

    if closes.empty:
        raise RuntimeError(f"No valid close price for {symbol}")

    return float(closes.iloc[-1])


def collect() -> None:
    observed_at = datetime.now(IST)

    values = {
        name: get_latest_close(symbol)
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
