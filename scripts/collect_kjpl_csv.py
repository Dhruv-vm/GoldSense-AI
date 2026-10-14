from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

KJPL_URL = "http://www.kjpl.in/"
OUTPUT = Path("data/kjpl/kjpl_rates.csv")
IST = ZoneInfo("Asia/Kolkata")

# Bounds for sanity validation
MIN_REASONABLE_GOLD = 5000.0   # INR / gram
MAX_REASONABLE_GOLD = 50000.0  # INR / gram
MIN_REASONABLE_SILVER = 50.0   # INR / gram
MAX_REASONABLE_SILVER = 5000.0 # INR / gram


def parse_rate(text: str | None) -> float | None:
    """Parse numeric gold/silver rate string into a float."""
    if not text:
        return None
    try:
        clean = text.replace(",", "").strip()
        val = float(clean)
        return val if val > 0 else None
    except (ValueError, AttributeError):
        return None


def validate_rates(
    gold: float | None,
    silver: float | None,
    published_time: str | None,
) -> tuple[bool, str]:
    """Validate that scraped rates and published time are sound and reasonable."""
    if gold is None:
        return False, "Gold rate is missing or could not be parsed."
    if not (MIN_REASONABLE_GOLD <= gold <= MAX_REASONABLE_GOLD):
        return False, f"Gold rate ₹{gold:.2f}/g is outside reasonable bounds [{MIN_REASONABLE_GOLD}, {MAX_REASONABLE_GOLD}]."
    if silver is not None and not (MIN_REASONABLE_SILVER <= silver <= MAX_REASONABLE_SILVER):
        return False, f"Silver rate ₹{silver:.2f}/g is outside reasonable bounds [{MIN_REASONABLE_SILVER}, {MAX_REASONABLE_SILVER}]."
    if not published_time or len(published_time.strip()) < 4:
        return False, "Published timestamp is missing or malformed."
    if not re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)\b", published_time, re.IGNORECASE):
        return False, f"Published time '{published_time}' does not contain a recognizable clock time format."
    return True, "Valid"


def check_event_status(
    published_time: str | None,
    gold: float,
    silver: float | None,
    observed_at: datetime,
    csv_path: Path = OUTPUT,
) -> tuple[bool, str]:
    """
    Check whether this KJPL rate has already been recorded.
    Returns (is_duplicate, reason).
    """
    if not csv_path.exists():
        return False, "CSV file does not exist yet."

    rows: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    if not rows:
        return False, "CSV file is empty."

    # 1. Check against latest row:
    # If the website still has the exact same published_time and rates as the latest recorded event,
    # then no new market publication event has occurred on KJPL.
    latest = rows[-1]
    latest_pub = latest.get("published_time")
    try:
        latest_gold = float(latest.get("gold_mjdta", 0))
    except (ValueError, TypeError):
        latest_gold = None

    try:
        latest_silver = float(latest["silver_mjdta"]) if latest.get("silver_mjdta") else None
    except (ValueError, TypeError):
        latest_silver = None

    if latest_pub == published_time and latest_gold == gold and latest_silver == silver:
        return True, f"Identical to latest recorded event (Published='{published_time}', Gold=₹{gold:,.2f})"

    # 2. Check for duplicate within the same calendar day (IST):
    # Same day with identical published time and gold rate should not be logged twice.
    obs_date_str = observed_at.astimezone(IST).strftime("%Y-%m-%d")
    for row in rows:
        row_obs = row.get("observed_at", "")
        if row_obs.startswith(obs_date_str) and row.get("published_time") == published_time:
            try:
                row_gold = float(row.get("gold_mjdta", 0))
            except (ValueError, TypeError):
                continue
            if row_gold == gold:
                return True, f"Already recorded today ({obs_date_str}) with Published='{published_time}' and Gold=₹{gold:,.2f}"

    return False, "New event detected."


def event_exists(
    published_time: str | None,
    gold: float,
    silver: float | None,
    csv_path: Path = OUTPUT,
) -> bool:
    """Backward compatibility wrapper for event_exists."""
    is_dup, _ = check_event_status(published_time, gold, silver, datetime.now(IST), csv_path=csv_path)
    return is_dup


def append_rate_to_csv(
    observed_at: datetime,
    published_time: str | None,
    gold: float,
    silver: float | None,
    csv_path: Path = OUTPUT,
) -> None:
    """Append a validated new KJPL rate record to CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0

    with csv_path.open("a", newline="", encoding="utf-8") as file:
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


def collect(csv_path: Path = OUTPUT, session: requests.Session | None = None) -> bool:
    """
    Main collection execution routine.
    Fetches the live KJPL rate, validates fields, checks for duplicates, and records fresh events.
    Returns True if a new event was recorded, False otherwise.
    """
    now_utc = datetime.now(timezone.utc)
    observed_at = datetime.now(IST)
    event_trigger = os.environ.get("GITHUB_EVENT_NAME", "local/manual")

    print("=" * 70)
    print(f"[KJPL COLLECTOR] Execution Time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"[KJPL COLLECTOR] Execution Time (IST): {observed_at.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"[KJPL COLLECTOR] Trigger: {event_trigger}")
    print(f"[KJPL COLLECTOR] Target CSV: {csv_path}")
    print("=" * 70)

    http = session or requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = http.get(KJPL_URL, timeout=30, headers=headers)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[KJPL COLLECTOR] ERROR: Failed to fetch {KJPL_URL}: {exc}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")
    gold_element = soup.select_one(".gold-rate")
    silver_element = soup.select_one(".silver-rate")
    time_element = soup.select_one(".mjdma_data")

    gold = parse_rate(gold_element.get_text(strip=True) if gold_element else None)
    silver = parse_rate(silver_element.get_text(strip=True) if silver_element else None)
    published_time = time_element.get_text(" ", strip=True) if time_element else None

    print(f"[KJPL COLLECTOR] Detected Raw Data:")
    print(f"  Published Clock Time : {published_time}")
    print(f"  Gold (₹/g)           : {gold}")
    print(f"  Silver (₹/g)         : {silver}")

    # Validate rates
    is_valid, val_reason = validate_rates(gold, silver, published_time)
    if not is_valid:
        print(f"[KJPL COLLECTOR] VALIDATION REJECTED: {val_reason}")
        raise ValueError(f"Invalid rate data: {val_reason}")

    # Deduplication check
    is_dup, dup_reason = check_event_status(
        published_time=published_time,
        gold=gold,  # type: ignore[arg-type]
        silver=silver,
        observed_at=observed_at,
        csv_path=csv_path,
    )

    if is_dup:
        print(f"[KJPL COLLECTOR] STATUS: RATE UNCHANGED / DUPLICATE DETECTED")
        print(f"  Reason: {dup_reason}")
        print(f"[KJPL COLLECTOR] Skipping CSV append (no redundant row created).")
        return False

    append_rate_to_csv(
        observed_at=observed_at,
        published_time=published_time,
        gold=gold,  # type: ignore[arg-type]
        silver=silver,
        csv_path=csv_path,
    )

    print(f"[KJPL COLLECTOR] STATUS: SUCCESS (NEW EVENT RECORDED)")
    print(f"  Published Time : {published_time}")
    print(f"  Observed At    : {observed_at.isoformat()}")
    print(f"  Gold Rate      : ₹{gold:,.2f}/g")
    if silver is not None:
        print(f"  Silver Rate    : ₹{silver:,.2f}/g")
    print(f"[KJPL COLLECTOR] Successfully saved to {csv_path}")
    return True


if __name__ == "__main__":
    collect()