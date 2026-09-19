from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


KJPL_URL = "http://www.kjpl.in/"
OUTPUT = Path("data/kjpl/kjpl_rates.csv")
IST = ZoneInfo("Asia/Kolkata")


def parse_rate(text: str) -> float | None:
    try:
        return float(text.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def collect() -> None:
    observed_at = datetime.now(IST)

    response = requests.get(
        KJPL_URL,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 GoldSense-AI Collector"},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    gold_element = soup.select_one(".gold-rate")
    silver_element = soup.select_one(".silver-rate")
    time_element = soup.select_one(".mjdma_data")

    gold = parse_rate(
        gold_element.get_text(strip=True) if gold_element else None
    )

    silver = parse_rate(
        silver_element.get_text(strip=True) if silver_element else None
    )

    published_time = (
        time_element.get_text(" ", strip=True)
        if time_element
        else None
    )

    if gold is None:
        raise RuntimeError("Could not find KJPL gold rate.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    file_exists = OUTPUT.exists()

    with OUTPUT.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "observed_at",
                "published_time",
                "gold_mjdta",
                "silver_mjdta",
                "source",
            ],
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "observed_at": observed_at.isoformat(),
                "published_time": published_time,
                "gold_mjdta": gold,
                "silver_mjdta": silver,
                "source": "KJPL",
            }
        )

    print(
        f"[KJPL CSV] {observed_at.isoformat()} "
        f"Gold=₹{gold:,.2f}/g "
        f"Silver=₹{silver:,.2f}/g"
        if silver is not None
        else
        f"[KJPL CSV] {observed_at.isoformat()} "
        f"Gold=₹{gold:,.2f}/g"
    )


if __name__ == "__main__":
    collect()
