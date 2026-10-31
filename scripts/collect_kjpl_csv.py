from __future__ import annotations

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import requests
from bs4 import BeautifulSoup

# Ensure backend is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.kjpl.city_parser import parse_kjpl_all_city_rates
from app.services.kjpl.persistence import (
    persist_parsed_payload,
    CITY_RATES_CSV,
    KJPL_RATES_CSV,
)
from app.models.bullion import CollectorRun, DataSourceStatus

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
    csv_path: Path = KJPL_RATES_CSV,
) -> tuple[bool, str]:
    """Check whether this benchmark rate has already been recorded in legacy CSV."""
    if not csv_path.exists():
        return False, "CSV file does not exist yet."

    rows: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        return False, "CSV file is empty."

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

    obs_date_str = observed_at.astimezone(IST).strftime("%Y-%m-%d")
    for row in rows:
        row_obs = row.get("observed_at", "")
        if row_obs.startswith(obs_date_str) and row.get("published_time") == published_time:
            return True, f"Already recorded event today with same publication timestamp ({published_time})"

    return False, "New event detected."


def append_rate_to_csv(
    observed_at: datetime,
    published_time: str | None,
    gold: float,
    silver: float | None,
    csv_path: Path = KJPL_RATES_CSV,
) -> None:
    """Append a validated new KJPL rate record to legacy benchmark CSV."""
    csv_path = Path(csv_path)
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


def run_collection(
    source_url: str = KJPL_URL,
    html_override: str | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """
    Unified KJPL collection routine:
      1. Fetches live HTML from KJPL or uses html_override fixture.
      2. Parses MJDTA benchmarks and all available city-wise products (Chennai, Bengaluru, Mumbai, Coimbatore, Hyderabad).
      3. Validates prices, weights, units, and timestamps.
      4. Detects changed vs. unchanged prices.
      5. Records history and updates latest records in database (Supabase if DATABASE_URL configured, or local SQLite).
      6. Mirrors to data/kjpl/city_rates.csv and data/kjpl/kjpl_rates.csv for offline development resilience.
      7. Writes structured execution logs to collector_runs.
    """
    start_time = time.time()
    now_utc = datetime.now(timezone.utc)
    now_ist = datetime.now(IST)
    event_trigger = os.environ.get("GITHUB_EVENT_NAME", "local/manual")

    print("=" * 75)
    print(" [VMD BULLION] KJPL CITY-WISE DATA COLLECTION PIPELINE")
    print(f" Execution Time (UTC) : {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f" Execution Time (IST) : {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f" Trigger              : {event_trigger}")
    print(f" Source URL           : {source_url}")
    print("=" * 75)

    html_content = html_override
    if html_content is None:
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

        last_exc = None
        for attempt in range(1, 4):
            try:
                resp = http.get(source_url, timeout=30, headers=headers)
                resp.raise_for_status()
                html_content = resp.text
                break
            except Exception as exc:
                last_exc = exc
                print(f"[KJPL COLLECTOR] Fetch attempt {attempt}/3 failed: {exc}")
                if attempt < 3:
                    time.sleep(3)

        if html_content is None:
            duration = round(time.time() - start_time, 2)
            error_msg = f"HTTP fetch failed from {source_url} after 3 attempts: {last_exc}"
            print(f"[KJPL COLLECTOR] ERROR: {error_msg}")

            # Try logging failed run to DB if available
            try:
                from app.db.session import SessionLocal
                with SessionLocal() as s:
                    s.add(CollectorRun(
                        collector_name="KJPL_CITY_COLLECTOR",
                        status="FAILED",
                        records_extracted=0,
                        records_inserted=0,
                        records_changed=0,
                        duration_seconds=duration,
                        error_message=str(last_exc),
                        executed_at=now_utc,
                    ))
                    ds = s.query(DataSourceStatus).filter_by(source_name="KJPL").first()
                    if ds:
                        ds.last_failed_run = now_utc
                        ds.current_status = "DOWN"
                        ds.error_message = str(last_exc)
                        ds.updated_at = now_utc
                    s.commit()
            except Exception:
                pass

            raise last_exc

    # Parse all city-wise and benchmark rates
    payload = parse_kjpl_all_city_rates(html_content, reference_time=now_ist)

    print(f"[KJPL COLLECTOR] Successfully parsed {payload.raw_products_count} bullion products.")
    print(f"  Published Clock Time : {payload.source_updated_time}")
    print(f"  MJDTA Gold Benchmark : ₹{payload.mjdta_gold:,.2f}/g" if payload.mjdta_gold else "  MJDTA Gold: None")
    print(f"  MJDTA Silver         : ₹{payload.mjdta_silver:,.2f}/g" if payload.mjdta_silver else "  MJDTA Silver: None")

    for r in payload.city_rates:
        print(f"    • [{r.metal}] {r.city_code:<12} | {r.product_id:<16} | ₹{r.price:,.2f} ({r.unit})")

    # Persist parsed observations with change detection
    db_result = persist_parsed_payload(payload, source_url=source_url)
    duration = round(time.time() - start_time, 2)

    # Legacy kjpl_rates.csv sync: append benchmark rate if changed
    if payload.mjdta_gold:
        _sync_legacy_kjpl_csv(now_ist, payload.source_updated_time, payload.mjdta_gold, payload.mjdta_silver)

    # Log successful collector run in DB
    try:
        from app.db.session import SessionLocal
        with SessionLocal() as s:
            s.add(CollectorRun(
                collector_name="KJPL_CITY_COLLECTOR",
                status="SUCCESS",
                records_extracted=db_result.get("records_extracted", 0),
                records_inserted=db_result.get("records_inserted", 0),
                records_changed=db_result.get("records_changed", 0),
                duration_seconds=duration,
                error_message=None,
                executed_at=now_utc,
            ))
            s.commit()
    except Exception as e:
        print(f"[KJPL COLLECTOR] Run logging note: {e}")

    print("-" * 75)
    print(f"[KJPL COLLECTOR] Summary: Extracted={db_result.get('records_extracted')}, "
          f"Inserted={db_result.get('records_inserted')}, "
          f"Changed={db_result.get('records_changed')} in {duration}s.")
    print("=" * 75)

    return {
        "status": "SUCCESS",
        "duration_seconds": duration,
        "payload": payload,
        "persistence": db_result,
    }


def _sync_legacy_kjpl_csv(
    observed_at: datetime,
    published_time: str | None,
    gold: float,
    silver: float | None,
) -> None:
    """Keep legacy data/kjpl/kjpl_rates.csv synchronized for downstream ML pipeline."""
    if not KJPL_RATES_CSV.exists():
        return

    # Check last row
    with KJPL_RATES_CSV.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        if rows:
            latest = rows[-1]
            try:
                latest_gold = float(latest["gold_mjdta"])
                latest_silver = float(latest["silver_mjdta"]) if latest.get("silver_mjdta") else None
            except Exception:
                latest_gold = None
                latest_silver = None
            if latest.get("published_time") == published_time and latest_gold == gold and latest_silver == silver:
                return  # duplicate

    with KJPL_RATES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["observed_at", "published_time", "gold_mjdta", "silver_mjdta", "source"])
        writer.writerow({
            "observed_at": observed_at.isoformat(),
            "published_time": published_time,
            "gold_mjdta": gold,
            "silver_mjdta": silver,
            "source": "KJPL",
        })


# Backward compatibility alias
def collect(csv_path: Path = OUTPUT, session: requests.Session | None = None) -> bool | dict[str, Any]:
    """
    Backward-compatible collection entrypoint.
    If called with a custom csv_path (e.g. in test harness), runs the single-file collector.
    Otherwise runs full unified multi-city collection.
    """
    if csv_path != OUTPUT:
        http = session or requests.Session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = http.get(KJPL_URL, timeout=30, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        gold_el = soup.select_one(".gold-rate")
        silver_el = soup.select_one(".silver-rate")
        time_el = soup.select_one(".mjdma_data")

        gold = parse_rate(gold_el.get_text(strip=True) if gold_el else None)
        silver = parse_rate(silver_el.get_text(strip=True) if silver_el else None)
        pub_time = time_el.get_text(" ", strip=True) if time_el else None

        valid, _ = validate_rates(gold, silver, pub_time)
        if not valid:
            return False

        observed_at = datetime.now(IST)
        is_dup, _ = check_event_status(pub_time, gold, silver, observed_at, csv_path=csv_path)
        if is_dup:
            return False

        append_rate_to_csv(observed_at, pub_time, gold, silver, csv_path=csv_path)
        return True

    res = run_collection(session=session)
    return res.get("status") == "SUCCESS"


if __name__ == "__main__":
    run_collection()
