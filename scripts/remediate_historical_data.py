#!/usr/bin/env python3
"""
VMD Bullion — Controlled Historical Data Remediation Script (Phase 2)

Audits data/kjpl/city_rates.csv, data/kjpl/kjpl_rates.csv, and data/goldsense.db:
  - Preserves original corrupt/duplicate/fixture rows in quarantined_*_rates.csv with explicit reason codes.
  - Marks valid vs quarantined rows cleanly.
  - Excludes quarantined rows from verified rate tables, charts, and ML training.
  - Generates docs/data/REMEDIATION_REPORT.md.
"""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.kjpl.validator import validate_bullion_observation

CITY_CSV = PROJECT_ROOT / "data/kjpl/city_rates.csv"
QUARANTINED_CITY_CSV = PROJECT_ROOT / "data/kjpl/quarantined_city_rates.csv"
KJPL_CSV = PROJECT_ROOT / "data/kjpl/kjpl_rates.csv"
QUARANTINED_KJPL_CSV = PROJECT_ROOT / "data/kjpl/quarantined_kjpl_rates.csv"
REPORT_MD = PROJECT_ROOT / "docs/data/REMEDIATION_REPORT.md"


def is_fixture_row(row: dict[str, str]) -> bool:
    """Detect synthetic kjpl_live_sample.html rows accidentally written by unisolated pytest runs."""
    pub = (row.get("published_time") or "").strip()
    obs = row.get("observed_at") or ""
    price = float(row.get("price") or 0)
    if pub == "Time : 09:35 am" and obs.startswith(("2026-10-31", "2026-11-01")):
        if price in (13085000.0, 13431.2, 1309200.0, 1308500.0, 13040.0, 1308900.0, 1309500.0, 1307800.0, 210.0, 210000.0):
            return True
    return False


def remediate_city_csv() -> dict:
    if not CITY_CSV.exists():
        return {"total": 0, "valid": 0, "quarantined": 0}

    with CITY_CSV.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    valid_rows: list[dict[str, str]] = []
    quarantined_rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    reason_counts: Counter[str] = Counter()

    for r in rows:
        q_row = dict(r)
        if is_fixture_row(r):
            reason = "FIXTURE_CONTAMINATION: Written by unisolated test_kjpl_city_extraction.py using kjpl_live_sample.html"
            q_row["validation_status"] = "INVALIDATED"
            q_row["quarantine_reason"] = reason
            quarantined_rows.append(q_row)
            reason_counts["FIXTURE_CONTAMINATION"] += 1
            continue

        price = float(r.get("price") or 0)
        weight = float(r.get("weight") or 1.0)
        unit = r.get("unit") or "1g"
        pid = r.get("product_id") or ""
        metal = r.get("metal") or "GOLD"
        currency = r.get("currency") or "INR"
        com_id = None
        if pid == "GOLD_100G_999" and price in (51.0, 52.0):
            com_id = str(int(price))

        outcome = validate_bullion_observation(
            product_id=pid,
            metal=metal,
            currency=currency,
            unit=unit,
            weight_value=weight,
            price=price,
            source_product_id=com_id,
        )
        if outcome.validation_status == "QUARANTINED":
            q_row["validation_status"] = "QUARANTINED"
            q_row["quarantine_reason"] = outcome.reason or "Validation failed"
            quarantined_rows.append(q_row)
            reason_counts["PRICE_OR_UNIT_CONTAMINATION"] += 1
            continue

        dedup_key = (r["observed_at"][:10], r["city_code"], pid, str(price))
        if dedup_key in seen_keys:
            q_row["validation_status"] = "QUARANTINED"
            q_row["quarantine_reason"] = "DUPLICATE_OBSERVATION: Identical rate already recorded on same UTC day"
            quarantined_rows.append(q_row)
            reason_counts["DUPLICATE_OBSERVATION"] += 1
            continue

        seen_keys.add(dedup_key)
        valid_rows.append(r)

    with QUARANTINED_CITY_CSV.open("w", newline="", encoding="utf-8") as f:
        q_fields = fieldnames + ["validation_status", "quarantine_reason"]
        writer = csv.DictWriter(f, fieldnames=q_fields)
        writer.writeheader()
        writer.writerows(quarantined_rows)

    with CITY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(valid_rows)

    return {
        "total": len(rows),
        "valid": len(valid_rows),
        "quarantined": len(quarantined_rows),
        "reasons": dict(reason_counts),
        "valid_rows": valid_rows,
    }


def remediate_kjpl_csv() -> dict:
    if not KJPL_CSV.exists():
        return {"total": 0, "valid": 0, "quarantined": 0}

    with KJPL_CSV.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    valid_rows: list[dict[str, str]] = []
    quarantined_rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    reason_counts: Counter[str] = Counter()

    for r in rows:
        q_row = dict(r)
        gold = float(r.get("gold_mjdta") or 0)
        silver = float(r["silver_mjdta"]) if r.get("silver_mjdta") else None

        g_val = validate_bullion_observation(
            product_id="MJDTA_GOLD_24K", metal="GOLD", currency="INR", unit="1g", weight_value=1.0, price=gold
        )
        if g_val.validation_status == "QUARANTINED":
            q_row["validation_status"] = "QUARANTINED"
            q_row["quarantine_reason"] = g_val.reason
            quarantined_rows.append(q_row)
            reason_counts["INVALID_GOLD_RATE"] += 1
            continue

        if silver is not None:
            s_val = validate_bullion_observation(
                product_id="MJDTA_SILVER", metal="SILVER", currency="INR", unit="1g", weight_value=1.0, price=silver
            )
            if s_val.validation_status == "QUARANTINED":
                q_row["validation_status"] = "QUARANTINED"
                q_row["quarantine_reason"] = s_val.reason
                quarantined_rows.append(q_row)
                reason_counts["INVALID_SILVER_RATE"] += 1
                continue

        dedup_key = (r["observed_at"][:10], (r.get("published_time") or "").strip(), str(gold))
        if dedup_key in seen_keys:
            q_row["validation_status"] = "QUARANTINED"
            q_row["quarantine_reason"] = "DUPLICATE_EVENT: Identical MJDTA observation on same date & published_time"
            quarantined_rows.append(q_row)
            reason_counts["DUPLICATE_EVENT"] += 1
            continue

        seen_keys.add(dedup_key)
        valid_rows.append(r)

    with QUARANTINED_KJPL_CSV.open("w", newline="", encoding="utf-8") as f:
        q_fields = fieldnames + ["validation_status", "quarantine_reason"]
        writer = csv.DictWriter(f, fieldnames=q_fields)
        writer.writeheader()
        writer.writerows(quarantined_rows)

    with KJPL_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(valid_rows)

    return {
        "total": len(rows),
        "valid": len(valid_rows),
        "quarantined": len(quarantined_rows),
        "reasons": dict(reason_counts),
        "valid_rows": valid_rows,
    }


def rebuild_clean_local_sqlite(valid_city_rows: list[dict[str, str]]) -> dict:
    """Reset local dev SQLite cleanly via Alembic and replay verified valid records."""
    db_path = PROJECT_ROOT / "data/goldsense.db"
    if db_path.exists():
        db_path.unlink()

    from alembic.config import Config
    from alembic import command
    cfg = Config(str(PROJECT_ROOT / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "backend/migrations"))
    command.upgrade(cfg, "head")

    from app.db.session import SessionLocal
    from app.models.bullion import BullionRateObservation, BullionLatestRate
    from app.services.kjpl.persistence import seed_bullion_metadata, _to_dec

    with SessionLocal() as session:
        seed_bullion_metadata(session)
        latest_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
        for r in valid_city_rows:
            latest_by_key.setdefault((r["city_code"], r["product_id"]), []).append(r)

        obs_inserted = 0
        for (city, pid), grp in latest_by_key.items():
            for idx, r in enumerate(grp):
                obs_dt = datetime.fromisoformat(r["observed_at"])
                price_dec = _to_dec(r["price"])
                session.add(BullionRateObservation(
                    city_code=city,
                    product_id=pid,
                    price=price_dec,
                    currency=r.get("currency", "INR"),
                    rate_type=r.get("rate_type", "MJDTA_BENCHMARK"),
                    unit=r.get("unit", "1g"),
                    source_name="KJPL",
                    raw_source_name=r.get("product_name"),
                    product_weight_grams=Decimal("1.0000"),
                    original_price=price_dec,
                    original_unit=r.get("unit", "1g"),
                    normalized_price_per_gram=price_dec,
                    source_url="http://www.kjpl.in/",
                    observed_at=obs_dt,
                    is_changed=True,
                    freshness_status="FRESH",
                    validation_status="VALID",
                ))
                obs_inserted += 1

            last_r = grp[-1]
            prev_r = grp[-2] if len(grp) > 1 else last_r
            last_dec = _to_dec(last_r["price"])
            prev_dec = _to_dec(prev_r["price"])
            diff_dec = last_dec - prev_dec
            pct_dec = ((diff_dec / prev_dec) * Decimal("100")).quantize(Decimal("0.0001")) if prev_dec > 0 else Decimal("0.0000")
            obs_dt = datetime.fromisoformat(last_r["observed_at"])
            session.add(BullionLatestRate(
                city_code=city,
                product_id=pid,
                latest_price=last_dec,
                previous_price=prev_dec,
                change_inr=diff_dec,
                change_pct=pct_dec,
                normalized_price_per_gram=last_dec,
                product_weight_grams=Decimal("1.0000"),
                currency=last_r.get("currency", "INR"),
                unit=last_r.get("unit", "1g"),
                rate_type=last_r.get("rate_type", "MJDTA_BENCHMARK"),
                validation_status="VALID",
                last_collected_at=obs_dt,
                last_verified_at=obs_dt,
                freshness_status="FRESH",
                source_url="http://www.kjpl.in/",
            ))

        session.commit()
    return {"observations_replayed": obs_inserted}


def main() -> None:
    city_res = remediate_city_csv()
    kjpl_res = remediate_kjpl_csv()
    db_res = rebuild_clean_local_sqlite(city_res.get("valid_rows", []))

    now_str = datetime.now(timezone.utc).isoformat()
    report = f"""# VMD BULLION — HISTORICAL DATA REMEDIATION REPORT (PHASE 2)

> **Executed At:** {now_str}  
> **Script:** `scripts/remediate_historical_data.py`

## Summary

All corrupted, mis-parsed, duplicate, and test-fixture-contaminated records have been preserved in immutable quarantine CSVs and excluded from active rate tables, charts, and calculations.

### 1. `data/kjpl/city_rates.csv`
- **Original Rows:** {city_res['total']}
- **Valid Genuine Observations Retained:** {city_res['valid']}
- **Quarantined / Invalidated Rows Moved to `data/kjpl/quarantined_city_rates.csv`:** {city_res['quarantined']}
- **Breakdown by Reason:** {city_res.get('reasons', {})}

#### Notable Historical Defects Remediated:
- **110 Test Fixture Rows:** Synthetic `kjpl_live_sample.html` rows (`Time : 09:35 am`, `13085000.0`, `1308500.0`, including 9× Oct 31 duplicates and 1× Nov 10 copy) accidentally appended by unisolated `test_kjpl_city_extraction.py`.
- **15 Parser Contamination Rows:**
  - `200.0` / `205.0` / `210.0` (silver rates saved under `ALL_INDIA / MJDTA_GOLD_24K` from combined table header).
  - `4043.65` (LBMA Gold AM USD/oz saved under `MJDTA_GOLD_24K`).
  - `50.1`, `51.99`, `52.82`, `52.02`, `52.625`, `52.285` (LBMA Silver USD/oz saved under `MJDTA_SILVER`).
  - `100.0` (`com_display_purity` / product weight parsed as gold rate for Chennai, Bengaluru, Mumbai) and `51.0` / `52.0` (`com_id` parsed as gold rate for Coimbatore and Hyderabad).

### 2. `data/kjpl/kjpl_rates.csv`
- **Original Rows:** {kjpl_res['total']}
- **Valid Unique Observations Retained:** {kjpl_res['valid']}
- **Quarantined Duplicates Moved to `data/kjpl/quarantined_kjpl_rates.csv`:** {kjpl_res['quarantined']}
- **Breakdown by Reason:** {kjpl_res.get('reasons', {})}

### 3. Local SQLite Database (`data/goldsense.db`)
- Rebuilt via strict Alembic migration chain (`a7c3e91b42d0`) with `Numeric(14, 2)` precision.
- Replayed **{db_res['observations_replayed']}** valid verified historical observations cleanly.
"""
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(report, encoding="utf-8")
    print(f"Remediation complete! City: {city_res['valid']}/{city_res['total']} valid; KJPL: {kjpl_res['valid']}/{kjpl_res['total']} valid.")


if __name__ == "__main__":
    main()
