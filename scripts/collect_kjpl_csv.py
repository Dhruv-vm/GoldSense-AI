from __future__ import annotations

import csv
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import requests
from bs4 import BeautifulSoup

# Enforce NullPool for short-lived collector scripts (GitHub Actions -> Neon)
os.environ.setdefault("DB_USE_NULLPOOL", "true")

# Ensure backend is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.kjpl.city_parser import parse_kjpl_all_city_rates, parse_kjpl_live_feed
from app.services.kjpl.persistence import (
    persist_parsed_payload,
    CITY_RATES_CSV,
    KJPL_RATES_CSV,
)
from app.models.bullion import CollectorRun, DataSourceStatus

KJPL_URL = "http://www.kjpl.in/"
KJPL_LIVE_TXT_URL = "http://www.kjpl.in/client/kjpl.txt"
KJPL_RPANEL_URL = "http://www.kjpl.in/index.php/C_booking/get_rpanel_data"
OUTPUT = Path("data/kjpl/kjpl_rates.csv")
IST = ZoneInfo("Asia/Kolkata")


# Bounds for sanity validation (aligned strictly with validator.py)
MIN_REASONABLE_GOLD = 5000.0   # INR / gram
MAX_REASONABLE_GOLD = 50000.0  # INR / gram
MIN_REASONABLE_SILVER = 80.0   # INR / gram (rejects LBMA USD/oz ~50-60)
MAX_REASONABLE_SILVER = 1500.0 # INR / gram


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


def _print_structured_item_logs(run_id: str, item_logs: list[dict[str, Any]]) -> None:
    """Emit structured per-city/per-product collector audit logs without secrets."""
    import json
    for entry in item_logs:
        record = {"collector_run_id": run_id, **entry}
        print(f"  [COLLECTOR_ITEM] {json.dumps(record, default=str)}")


def run_kjpl_snapshot_collection(
    session: requests.Session | None = None,
    *,
    txt_override: str | None = None,
    rpanel_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Interim one-time point-in-time KJPL Live Feed snapshot (kjpl.txt + get_rpanel_data).
    Kept strictly separate from Pipeline A MJDTA metrics (logs under KJPL_SNAPSHOT_COLLECTOR
    and source KJPL_LIVE). Disable in GitHub Actions once Oracle vmd-kjpl-worker is active.
    """
    start_time = time.time()
    now_utc = datetime.now(timezone.utc)
    now_ist = datetime.now(IST)
    run_id = uuid.uuid4().hex[:12]
    http = session or requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "text/plain,application/json,*/*;q=0.8",
    }
    live_txt = txt_override
    rpanel_json = rpanel_override
    if live_txt is None:
        try:
            txt_resp = http.get(KJPL_LIVE_TXT_URL, timeout=15, headers=headers)
            txt_resp.raise_for_status()
            live_txt = txt_resp.text
        except Exception as exc:
            print(f"[KJPL SNAPSHOT] kjpl.txt unavailable: {exc}")
            return {"status": "UPSTREAM_UNAVAILABLE", "run_id": run_id, "error": str(exc)}

    if rpanel_json is None:
        try:
            rp_resp = http.get(KJPL_RPANEL_URL, timeout=15, headers=headers)
            rp_resp.raise_for_status()
            rpanel_json = rp_resp.json()
        except Exception as exc:
            print(f"[KJPL SNAPSHOT] get_rpanel_data unavailable (non-fatal): {exc}")

    live_payload = parse_kjpl_live_feed(
        live_txt,
        rpanel_json=rpanel_json,
        reference_time=now_ist,
        source_label="KJPL_LIVE_TXT",
    )
    mirror_csv = os.environ.get("ENABLE_CSV_MIRROR", "false").lower() in ("true", "1", "yes")
    res = persist_parsed_payload(
        live_payload,
        source_url=KJPL_LIVE_TXT_URL,
        source_key="KJPL_LIVE",
        mirror_csv=mirror_csv,
    )
    duration = round(time.time() - start_time, 2)
    print(f"[KJPL SNAPSHOT] Parsed {live_payload.raw_products_count} valid ({len(live_payload.quarantined_rates)} quarantined).")
    _print_structured_item_logs(run_id, res.get("item_logs", []))

    try:
        from app.db.session import SessionLocal
        with SessionLocal() as s:
            s.add(CollectorRun(
                collector_name="KJPL_SNAPSHOT_COLLECTOR",
                run_id=run_id,
                status="SUCCESS",
                records_extracted=res.get("records_extracted", 0),
                records_inserted=res.get("records_inserted", 0),
                records_changed=res.get("records_changed", 0),
                records_quarantined=res.get("records_quarantined", 0),
                duration_seconds=duration,
                error_message=None,
                executed_at=now_utc,
            ))
            s.commit()
    except Exception as e:
        print(f"[KJPL SNAPSHOT] Run logging note: {e}")

    return {
        "status": "SUCCESS",
        "run_id": run_id,
        "duration_seconds": duration,
        "live_payload": live_payload,
        "persistence": res,
    }


def run_collection(
    source_url: str = KJPL_URL,
    html_override: str | None = None,
    session: requests.Session | None = None,
    *,
    txt_override: str | None = None,
    rpanel_override: dict[str, Any] | None = None,
    include_live_snapshot: bool | None = None,
) -> dict[str, Any]:
    """
    Pipeline A — Scheduled KJPL MJDTA & LBMA Reference Collector:
      1. Strictly fetches live HTML from KJPL (MJDTA Gold/Silver excl./with GST & LBMA USD fixes).
      2. Persists validated Pipeline A records under KJPL_MJDTA / KJPL_MJDTA_COLLECTOR.
      3. Only executes the interim kjpl.txt snapshot as a separate CollectorRun if explicitly
         requested via include_live_snapshot=True, txt_override, or ENABLE_SCHEDULED_CITY_SNAPSHOT=true.
    """
    start_time = time.time()
    now_utc = datetime.now(timezone.utc)
    now_ist = datetime.now(IST)
    run_id = uuid.uuid4().hex[:12]
    event_trigger = os.environ.get("GITHUB_EVENT_NAME", "local/manual")
    env_snapshot = os.environ.get("ENABLE_SCHEDULED_CITY_SNAPSHOT", "false").lower() in ("true", "1", "yes")
    should_fetch_snapshot = (
        include_live_snapshot
        if include_live_snapshot is not None
        else (env_snapshot or txt_override is not None)
    )

    print("=" * 75)
    print(" [VMD BULLION] PIPELINE A — KJPL MJDTA & LBMA REFERENCE COLLECTOR")
    print(f" Collector Run ID     : {run_id}")
    print(f" Execution Time (UTC) : {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f" Execution Time (IST) : {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f" Trigger              : {event_trigger}")
    print(f" Source URL           : {source_url}")
    print("=" * 75)

    html_content = html_override
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

    if html_content is None:
        last_exc = None
        for attempt in range(1, 4):
            try:
                resp = http.get(source_url, timeout=30, headers=headers)
                resp.raise_for_status()
                html_content = resp.text
                break
            except Exception as exc:
                last_exc = exc
                print(f"[KJPL MJDTA] Fetch attempt {attempt}/3 failed: {exc}")
                if attempt < 3:
                    time.sleep(3)

        if html_content is None:
            duration = round(time.time() - start_time, 2)
            error_msg = f"HTTP fetch failed from {source_url} after 3 attempts: {last_exc}"
            print(f"[KJPL MJDTA] WARNING: {error_msg}")
            print("[KJPL MJDTA] Upstream temporarily unavailable. Retaining verified state.")

            try:
                from app.db.session import SessionLocal
                with SessionLocal() as s:
                    s.add(CollectorRun(
                        collector_name="KJPL_MJDTA_COLLECTOR",
                        run_id=run_id,
                        status="SOURCE_UNAVAILABLE",
                        records_extracted=0,
                        records_inserted=0,
                        records_changed=0,
                        records_quarantined=0,
                        duration_seconds=duration,
                        error_message=str(last_exc),
                        executed_at=now_utc,
                    ))
                    for sname in ("KJPL_MJDTA", "KJPL"):
                        ds = s.query(DataSourceStatus).filter_by(source_name=sname).first()
                        if ds:
                            ds.last_failed_run = now_utc
                            ds.current_status = "DOWN"
                            ds.error_message = str(last_exc)
                            ds.updated_at = now_utc
                    s.commit()
            except Exception:
                pass

            return {
                "status": "UPSTREAM_UNAVAILABLE",
                "run_id": run_id,
                "duration_seconds": duration,
                "error": str(last_exc),
            }

    payload = parse_kjpl_all_city_rates(html_content, reference_time=now_ist)

    print(f"[KJPL MJDTA] HTML MJDTA/LBMA parsed: {payload.raw_products_count} valid ({len(payload.quarantined_rates)} quarantined).")
    print(f"  Published Clock Time : {payload.source_updated_time}")
    print(f"  Source Published At  : {payload.source_updated_at}")
    print(f"  MJDTA Gold Benchmark : ₹{payload.mjdta_gold:,.2f}/g" if payload.mjdta_gold else "  MJDTA Gold: None")
    print(f"  MJDTA Silver         : ₹{payload.mjdta_silver:,.2f}/g" if payload.mjdta_silver else "  MJDTA Silver: None")

    mirror_csv = os.environ.get("ENABLE_CSV_MIRROR", "false").lower() in ("true", "1", "yes")
    db_result = persist_parsed_payload(
        payload,
        source_url=source_url,
        source_key="KJPL_MJDTA",
        mirror_csv=mirror_csv,
    )
    _print_structured_item_logs(run_id, db_result.get("item_logs", []))
    duration = round(time.time() - start_time, 2)

    if payload.mjdta_gold and mirror_csv:
        _sync_legacy_kjpl_csv(now_ist, payload.source_updated_time, payload.mjdta_gold, payload.mjdta_silver)

    try:
        from app.db.session import SessionLocal
        with SessionLocal() as s:
            s.add(CollectorRun(
                collector_name="KJPL_MJDTA_COLLECTOR",
                run_id=run_id,
                status="SUCCESS",
                records_extracted=db_result.get("records_extracted", 0),
                records_inserted=db_result.get("records_inserted", 0),
                records_changed=db_result.get("records_changed", 0),
                records_quarantined=db_result.get("records_quarantined", 0),
                duration_seconds=duration,
                error_message=None,
                executed_at=now_utc,
            ))
            s.commit()
    except Exception as e:
        print(f"[KJPL MJDTA] Run logging note: {e}")

    print("-" * 75)
    print(f"[KJPL MJDTA] Summary (run_id={run_id}): Extracted={db_result.get('records_extracted', 0)}, "
          f"Inserted={db_result.get('records_inserted', 0)}, "
          f"Changed={db_result.get('records_changed', 0)}, "
          f"Quarantined={db_result.get('records_quarantined', 0)} in {duration}s.")
    print("=" * 75)

    snapshot_res = None
    if should_fetch_snapshot:
        snapshot_res = run_kjpl_snapshot_collection(
            session=http,
            txt_override=txt_override,
            rpanel_override=rpanel_override,
        )

    snap_pers = snapshot_res.get("persistence", {}) if snapshot_res else {}
    return {
        "status": "SUCCESS",
        "run_id": run_id,
        "duration_seconds": duration,
        "payload": payload,
        "live_payload": snapshot_res.get("live_payload") if snapshot_res else None,
        "persistence": {
            "records_extracted": db_result.get("records_extracted", 0) + snap_pers.get("records_extracted", 0),
            "records_inserted": db_result.get("records_inserted", 0) + snap_pers.get("records_inserted", 0),
            "records_changed": db_result.get("records_changed", 0) + snap_pers.get("records_changed", 0),
            "records_quarantined": db_result.get("records_quarantined", 0) + snap_pers.get("records_quarantined", 0),
        },
        "mjdta_persistence": db_result,
        "snapshot_persistence": snap_pers if snapshot_res else None,
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
    import argparse

    parser = argparse.ArgumentParser(description="VMD Bullion Pipeline A (MJDTA) & Optional Snapshot CLI")
    parser.add_argument("--mjdta-only", action="store_true", help="Run strictly Pipeline A (MJDTA + LBMA HTML)")
    parser.add_argument("--snapshot-only", action="store_true", help="Run strictly interim one-time kjpl.txt snapshot")
    parser.add_argument("--with-snapshot", action="store_true", help="Run Pipeline A plus separate snapshot run")
    args = parser.parse_args()

    if args.snapshot_only:
        run_kjpl_snapshot_collection()
    elif args.with_snapshot:
        run_collection(include_live_snapshot=True)
    elif args.mjdta_only:
        run_collection(include_live_snapshot=False)
    else:
        run_collection()
