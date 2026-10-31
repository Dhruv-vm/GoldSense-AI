from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.bullion import (
    BullionCity,
    BullionProduct,
    BullionRateObservation,
    BullionLatestRate,
    CollectorRun,
    DataSourceStatus,
)
from app.services.kjpl.city_schemas import ParsedKJPLPayload, ParsedCityRate

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
CITY_RATES_CSV = PROJECT_ROOT / "data/kjpl/city_rates.csv"
KJPL_RATES_CSV = PROJECT_ROOT / "data/kjpl/kjpl_rates.csv"

# Pre-seeded reference definitions for 5 mandatory cities
DEFAULT_CITIES = [
    {"city_code": "CHENNAI", "display_name": "Chennai", "state": "Tamil Nadu", "sort_order": 1},
    {"city_code": "BENGALURU", "display_name": "Bengaluru", "state": "Karnataka", "sort_order": 2},
    {"city_code": "MUMBAI", "display_name": "Mumbai", "state": "Maharashtra", "sort_order": 3},
    {"city_code": "COIMBATORE", "display_name": "Coimbatore", "state": "Tamil Nadu", "sort_order": 4},
    {"city_code": "HYDERABAD", "display_name": "Hyderabad", "state": "Telangana", "sort_order": 5},
    {"city_code": "ALL_INDIA", "display_name": "National", "state": "All India", "sort_order": 6},
]

# Standard reference products
DEFAULT_PRODUCTS = [
    {"product_id": "GOLD_100G_999", "product_name": "Gold 100 GMS 999 Bar", "metal": "GOLD", "purity": 0.999, "weight": 100.0, "unit": "100g", "rate_type": "RETAIL"},
    {"product_id": "GOLD_1KG_9999", "product_name": "Gold 1KG 99.99 Pure Bar", "metal": "GOLD", "purity": 0.9999, "weight": 1.0, "unit": "1kg", "rate_type": "WHOLESALE"},
    {"product_id": "MJDTA_GOLD_24K", "product_name": "MJDTA Gold 24K Pure Benchmark", "metal": "GOLD", "purity": 0.999, "weight": 1.0, "unit": "1g", "rate_type": "MJDTA_BENCHMARK"},
    {"product_id": "MJDTA_SILVER", "product_name": "MJDTA Silver Benchmark", "metal": "SILVER", "purity": 0.999, "weight": 1.0, "unit": "1g", "rate_type": "MJDTA_BENCHMARK"},
    {"product_id": "SILVER_1KG_999", "product_name": "Silver 1KG 999 Bar", "metal": "SILVER", "purity": 0.999, "weight": 1.0, "unit": "1kg", "rate_type": "RETAIL"},
]


def seed_bullion_metadata(session: Any = None) -> None:
    """
    Ensure 5 mandatory cities and default bullion products exist in database.
    Idempotent and safe.
    """
    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        # Seed cities
        for c in DEFAULT_CITIES:
            existing = session.execute(
                select(BullionCity).where(BullionCity.city_code == c["city_code"])
            ).scalar_one_or_none()
            if not existing:
                session.add(BullionCity(
                    city_code=c["city_code"],
                    display_name=c["display_name"],
                    state=c["state"],
                    is_active=True,
                    sort_order=c["sort_order"],
                ))

        # Seed products
        for p in DEFAULT_PRODUCTS:
            existing = session.execute(
                select(BullionProduct).where(BullionProduct.product_id == p["product_id"])
            ).scalar_one_or_none()
            if not existing:
                session.add(BullionProduct(
                    product_id=p["product_id"],
                    product_name=p["product_name"],
                    metal=p["metal"],
                    purity=p["purity"],
                    weight=p["weight"],
                    unit=p["unit"],
                    rate_type=p["rate_type"],
                    is_active=True,
                ))

        # Seed Data Source Status
        kjpl_status = session.execute(
            select(DataSourceStatus).where(DataSourceStatus.source_name == "KJPL")
        ).scalar_one_or_none()
        if not kjpl_status:
            session.add(DataSourceStatus(
                source_name="KJPL",
                current_status="OPERATIONAL",
                updated_at=datetime.now(timezone.utc),
            ))

        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[METADATA SEED] Note: {e}")
    finally:
        if own_session:
            session.close()


def persist_parsed_payload(
    payload: ParsedKJPLPayload,
    source_url: str = "http://www.kjpl.in/",
    session: Any = None,
) -> dict[str, Any]:
    """
    Atomically updates Supabase / PostgreSQL / SQLite and local CSV mirror:
      1. Compares newly parsed city rates against previous latest rates.
      2. If price changed: inserts new historical observation, updates latest_rates with change_inr & change_pct.
      3. If price unchanged: updates last_verified_at without generating artificial price volatility.
      4. Mirrors observations to data/kjpl/city_rates.csv for offline development resilience.
    """
    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    seed_bullion_metadata(session)

    inserted_count = 0
    changed_count = 0
    now_utc = datetime.now(timezone.utc)
    csv_rows_to_append: list[dict[str, Any]] = []

    try:
        for rate in payload.city_rates:
            # Check latest rate record in DB
            stmt = select(BullionLatestRate).where(
                BullionLatestRate.city_code == rate.city_code,
                BullionLatestRate.product_id == rate.product_id,
            )
            latest_record = session.execute(stmt).scalar_one_or_none()

            price_changed = False
            prev_price = None

            if latest_record is None:
                # Brand new record
                price_changed = True
                prev_price = rate.price
                latest_record = BullionLatestRate(
                    city_code=rate.city_code,
                    product_id=rate.product_id,
                    latest_price=rate.price,
                    previous_price=rate.price,
                    change_inr=0.0,
                    change_pct=0.0,
                    currency=rate.currency,
                    unit=rate.unit,
                    rate_type=rate.rate_type,
                    source_published_at=payload.source_updated_at,
                    last_collected_at=now_utc,
                    last_verified_at=now_utc,
                    freshness_status="FRESH",
                    source_url=source_url,
                )
                session.add(latest_record)
                changed_count += 1
            else:
                prev_price = latest_record.latest_price
                if abs(latest_record.latest_price - rate.price) > 0.001:
                    price_changed = True
                    change_inr = round(rate.price - latest_record.latest_price, 2)
                    change_pct = round((change_inr / latest_record.latest_price) * 100, 2) if latest_record.latest_price > 0 else 0.0
                    latest_record.previous_price = latest_record.latest_price
                    latest_record.latest_price = rate.price
                    latest_record.change_inr = change_inr
                    latest_record.change_pct = change_pct
                    latest_record.source_published_at = payload.source_updated_at
                    latest_record.last_collected_at = now_utc
                    changed_count += 1
                else:
                    # Unchanged: retain fixed price, bump verification time
                    price_changed = False

                latest_record.last_verified_at = now_utc
                latest_record.freshness_status = "FRESH"

            # Insert historical observation if changed or if first time seeing this product
            if price_changed:
                obs = BullionRateObservation(
                    city_code=rate.city_code,
                    product_id=rate.product_id,
                    price=rate.price,
                    currency=rate.currency,
                    rate_type=rate.rate_type,
                    unit=rate.unit,
                    source_url=source_url,
                    source_published_at=payload.source_updated_at,
                    observed_at=now_utc,
                    is_changed=True,
                    freshness_status="FRESH",
                )
                session.add(obs)
                inserted_count += 1

                csv_rows_to_append.append({
                    "observed_at": now_utc.isoformat(),
                    "city_code": rate.city_code,
                    "city_display_name": rate.city_display_name,
                    "product_id": rate.product_id,
                    "product_name": rate.product_name,
                    "metal": rate.metal,
                    "purity": rate.purity,
                    "weight": rate.weight,
                    "unit": rate.unit,
                    "price": rate.price,
                    "currency": rate.currency,
                    "rate_type": rate.rate_type,
                    "published_time": payload.source_updated_time or "",
                    "source": "KJPL",
                })

        # Update data source status
        ds_stmt = select(DataSourceStatus).where(DataSourceStatus.source_name == "KJPL")
        ds_record = session.execute(ds_stmt).scalar_one_or_none()
        if ds_record:
            ds_record.last_successful_run = now_utc
            ds_record.current_status = "OPERATIONAL"
            ds_record.error_message = None
            ds_record.updated_at = now_utc

        session.commit()

        # Mirror to CSV file
        if csv_rows_to_append:
            CITY_RATES_CSV.parent.mkdir(parents=True, exist_ok=True)
            file_exists = CITY_RATES_CSV.exists() and CITY_RATES_CSV.stat().st_size > 0
            with CITY_RATES_CSV.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "observed_at", "city_code", "city_display_name", "product_id",
                    "product_name", "metal", "purity", "weight", "unit", "price",
                    "currency", "rate_type", "published_time", "source"
                ])
                if not file_exists:
                    writer.writeheader()
                for row in csv_rows_to_append:
                    writer.writerow(row)

        return {
            "status": "SUCCESS",
            "records_extracted": len(payload.city_rates),
            "records_inserted": inserted_count,
            "records_changed": changed_count,
            "timestamp": now_utc.isoformat(),
        }

    except Exception as e:
        session.rollback()
        raise e
    finally:
        if own_session:
            session.close()
