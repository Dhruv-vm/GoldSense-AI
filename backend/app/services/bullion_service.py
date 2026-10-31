from __future__ import annotations

import csv
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, desc

from app.db.session import SessionLocal, DATABASE_URL, IS_POSTGRES
from app.models.bullion import (
    BullionCity,
    BullionProduct,
    BullionRateObservation,
    BullionLatestRate,
    CollectorRun,
    DataSourceStatus,
)
from app.services.data_service import (
    get_latest_market_from_csv,
    get_freshness_details,
    TROY_OUNCE_GRAMS,
)

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CITY_RATES_CSV = PROJECT_ROOT / "data/kjpl/city_rates.csv"
KJPL_RATES_CSV = PROJECT_ROOT / "data/kjpl/kjpl_rates.csv"

MANDATORY_CITIES = [
    {"city_code": "CHENNAI", "display_name": "Chennai", "state": "Tamil Nadu", "sort_order": 1, "is_default": True},
    {"city_code": "BENGALURU", "display_name": "Bengaluru", "state": "Karnataka", "sort_order": 2, "is_default": False},
    {"city_code": "MUMBAI", "display_name": "Mumbai", "state": "Maharashtra", "sort_order": 3, "is_default": False},
    {"city_code": "COIMBATORE", "display_name": "Coimbatore", "state": "Tamil Nadu", "sort_order": 4, "is_default": False},
    {"city_code": "HYDERABAD", "display_name": "Hyderabad", "state": "Telangana", "sort_order": 5, "is_default": False},
    {"city_code": "ALL_INDIA", "display_name": "National", "state": "All India", "sort_order": 6, "is_default": False},
]


def normalize_city_code(city_input: str) -> str:
    """Normalize city query param into canonical uppercase code."""
    c = city_input.strip().upper()
    if c in ("BANGALORE", "BLR"):
        return "BENGALURU"
    if c in ("MAA", "MADRAS"):
        return "CHENNAI"
    if c in ("BOM", "BOMBAY"):
        return "MUMBAI"
    if c in ("CJB",):
        return "COIMBATORE"
    if c in ("HYD",):
        return "HYDERABAD"
    if c in ("ALL", "NATIONAL", "ALL_INDIA", "ALL-INDIA"):
        return "ALL_INDIA"
    return c


def get_all_cities() -> list[dict[str, Any]]:
    """Return all configured cities with priority order and metadata."""
    db = SessionLocal()
    try:
        results = db.execute(select(BullionCity).order_by(BullionCity.sort_order)).scalars().all()
        if results:
            return [
                {
                    "city_code": c.city_code,
                    "display_name": c.display_name,
                    "state": c.state,
                    "is_active": c.is_active,
                    "sort_order": c.sort_order,
                    "is_default": (c.city_code == "CHENNAI"),
                }
                for c in results
            ]
    except Exception:
        pass
    finally:
        db.close()

    return MANDATORY_CITIES


def _read_latest_rates_from_csv() -> list[dict[str, Any]]:
    """Fallback reader parsing data/kjpl/city_rates.csv."""
    if not CITY_RATES_CSV.exists():
        return []

    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    with CITY_RATES_CSV.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row["city_code"]
            prod = row["product_id"]
            latest_by_key[(city, prod)] = row

    items: list[dict[str, Any]] = []
    for (city, prod), row in latest_by_key.items():
        price = float(row["price"])
        weight = float(row.get("weight", 1.0))
        per_gram = round(price / weight, 2) if weight > 0 else price
        obs_dt = datetime.fromisoformat(row["observed_at"])
        freshness = get_freshness_details(obs_dt)

        items.append({
            "city_code": city,
            "city_display_name": row.get("city_display_name", city),
            "product_id": prod,
            "product_name": row.get("product_name", prod),
            "metal": row.get("metal", "GOLD"),
            "purity": float(row.get("purity", 0.999)),
            "weight": weight,
            "unit": row.get("unit", "100g"),
            "rate_type": row.get("rate_type", "RETAIL"),
            "latest_price": price,
            "previous_price": price,
            "change_inr": 0.0,
            "change_pct": 0.0,
            "per_gram_price": per_gram,
            "currency": row.get("currency", "INR"),
            "source_updated_time": row.get("published_time", "N/A"),
            "observed_at": obs_dt.isoformat(),
            "last_verified_at": obs_dt.isoformat(),
            "freshness": freshness["status"],
            "age_hours": freshness["age_hours"],
            "age_display": freshness["age_display"],
            "source_url": "http://www.kjpl.in/",
        })
    return items


def get_latest_city_rates(
    city_code: str | None = None,
    metal: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get all current rates with product details, source publication timestamp,
    verification timestamp, and change indicators.
    """
    db = SessionLocal()
    rates: list[dict[str, Any]] = []
    try:
        stmt = (
            select(BullionLatestRate, BullionProduct, BullionCity)
            .join(BullionProduct, BullionLatestRate.product_id == BullionProduct.product_id)
            .join(BullionCity, BullionLatestRate.city_code == BullionCity.city_code)
            .order_by(BullionCity.sort_order, BullionProduct.metal, BullionProduct.product_name)
        )
        if city_code:
            norm_code = normalize_city_code(city_code)
            stmt = stmt.where(BullionLatestRate.city_code == norm_code)
        if metal:
            stmt = stmt.where(BullionProduct.metal == metal.upper())

        rows = db.execute(stmt).all()
        if rows:
            for rate_obj, prod_obj, city_obj in rows:
                weight = prod_obj.weight if prod_obj.weight > 0 else 1.0
                per_gram = round(rate_obj.latest_price / weight, 2)
                freshness = get_freshness_details(rate_obj.last_verified_at)

                rates.append({
                    "city_code": city_obj.city_code,
                    "city_display_name": city_obj.display_name,
                    "product_id": prod_obj.product_id,
                    "product_name": prod_obj.product_name,
                    "metal": prod_obj.metal,
                    "purity": prod_obj.purity,
                    "weight": prod_obj.weight,
                    "unit": prod_obj.unit,
                    "rate_type": prod_obj.rate_type,
                    "latest_price": rate_obj.latest_price,
                    "previous_price": rate_obj.previous_price,
                    "change_inr": rate_obj.change_inr,
                    "change_pct": rate_obj.change_pct,
                    "per_gram_price": per_gram,
                    "currency": rate_obj.currency,
                    "source_updated_time": rate_obj.source_published_at.strftime("%I:%M %p") if rate_obj.source_published_at else "N/A",
                    "observed_at": rate_obj.last_collected_at.isoformat(),
                    "last_verified_at": rate_obj.last_verified_at.isoformat(),
                    "freshness": freshness["status"],
                    "age_hours": freshness["age_hours"],
                    "age_display": freshness["age_display"],
                    "source_url": rate_obj.source_url,
                })
            return rates
    except Exception:
        pass
    finally:
        db.close()

    # Fallback to CSV
    csv_rates = _read_latest_rates_from_csv()
    if city_code:
        norm_code = normalize_city_code(city_code)
        csv_rates = [r for r in csv_rates if r["city_code"] == norm_code]
    if metal:
        csv_rates = [r for r in csv_rates if r["metal"] == metal.upper()]
    return csv_rates


def get_city_comparison() -> dict[str, Any]:
    """
    Produce institutional 5-city comparative matrix for retail benchmark (GOLD 100 GMS 999).
    Chennai is the baseline benchmark.
    Computes per-gram equivalent, spread in INR, spread in percentage.
    """
    all_rates = get_latest_city_rates()
    # Filter for GOLD_100G_999 across all 5 mandatory cities
    target_cities = ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]
    city_map: dict[str, dict[str, Any]] = {}

    for r in all_rates:
        if r["product_id"] == "GOLD_100G_999" and r["city_code"] in target_cities:
            city_map[r["city_code"]] = r

    # Determine Chennai benchmark baseline
    chennai_entry = city_map.get("CHENNAI")
    chennai_per_gram = chennai_entry["per_gram_price"] if chennai_entry else 0.0

    comparison_items: list[dict[str, Any]] = []
    for code in target_cities:
        entry = city_map.get(code)
        if entry:
            per_gram = entry["per_gram_price"]
            diff_inr = round(per_gram - chennai_per_gram, 2)
            diff_pct = round((diff_inr / chennai_per_gram) * 100, 3) if chennai_per_gram > 0 else 0.0

            comparison_items.append({
                "city_code": code,
                "city_display_name": entry["city_display_name"],
                "total_price_100g": entry["latest_price"],
                "per_gram_price": per_gram,
                "spread_vs_chennai_inr": diff_inr,
                "spread_vs_chennai_pct": diff_pct,
                "is_baseline": (code == "CHENNAI"),
                "source_updated_time": entry["source_updated_time"],
                "observed_at": entry["observed_at"],
                "last_verified_at": entry["last_verified_at"],
                "freshness": entry["freshness"],
            })
        else:
            # Placeholder for city if missing in current cycle
            display_name = next((c["display_name"] for c in MANDATORY_CITIES if c["city_code"] == code), code)
            comparison_items.append({
                "city_code": code,
                "city_display_name": display_name,
                "total_price_100g": None,
                "per_gram_price": None,
                "spread_vs_chennai_inr": None,
                "spread_vs_chennai_pct": None,
                "is_baseline": (code == "CHENNAI"),
                "source_updated_time": "N/A",
                "observed_at": None,
                "last_verified_at": None,
                "freshness": "UNAVAILABLE",
            })

    return {
        "benchmark_city": "CHENNAI",
        "benchmark_per_gram": chennai_per_gram,
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Bar",
        "cities": comparison_items,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_bullion_summary() -> dict[str, Any]:
    """
    Produce top-level summary for the VMD Bullion header and Overview dashboard:
      - Chennai MJDTA Gold 24K benchmark
      - MJDTA Silver benchmark
      - Wholesale Gold 1KG pure bar
      - 5-city retail summary
      - International COMEX / Forex parity
    """
    all_rates = get_latest_city_rates()

    # Find key products
    chennai_mjdta = next((r for r in all_rates if r["city_code"] == "CHENNAI" and r["product_id"] == "MJDTA_GOLD_24K"), None)
    silver_bench = next((r for r in all_rates if r["product_id"] == "MJDTA_SILVER"), None)
    wholesale_1kg = next((r for r in all_rates if r["product_id"] == "GOLD_1KG_9999"), None)

    # 5-city retail tape
    target_cities = ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]
    city_tape = []
    for c in target_cities:
        entry = next((r for r in all_rates if r["city_code"] == c and r["product_id"] == "GOLD_100G_999"), None)
        if entry:
            city_tape.append({
                "city_code": entry["city_code"],
                "city_name": entry["city_display_name"],
                "price_100g": entry["latest_price"],
                "per_gram": entry["per_gram_price"],
                "source_updated_time": entry["source_updated_time"],
                "freshness": entry["freshness"],
            })

    # International market context
    market = get_latest_market_from_csv()
    parity_info = None
    if market and chennai_mjdta:
        xau = market["xauusd"]
        usdinr = market["usdinr"]
        customs_duty_pct = 0.06  # Indian effective import duty
        cess_pct = 0.01          # AIDC
        gst_pct = 0.03           # GST

        import_cost_per_gram = (xau * usdinr) / TROY_OUNCE_GRAMS
        landed_duty_paid = import_cost_per_gram * (1 + customs_duty_pct + cess_pct)
        domestic_spot = chennai_mjdta["latest_price"]
        domestic_premium_inr = round(domestic_spot - landed_duty_paid, 2)
        domestic_premium_pct = round((domestic_premium_inr / landed_duty_paid) * 100, 2)

        parity_info = {
            "xauusd": xau,
            "xagusd": market["xagusd"],
            "usdinr": usdinr,
            "import_cost_per_gram": round(import_cost_per_gram, 2),
            "landed_duty_paid_per_gram": round(landed_duty_paid, 2),
            "domestic_premium_inr": domestic_premium_inr,
            "domestic_premium_pct": domestic_premium_pct,
            "market_freshness": market["freshness"],
        }

    return {
        "terminal_title": "VMD Bullion Intelligence Terminal",
        "default_city": "CHENNAI",
        "benchmark_gold_24k": chennai_mjdta,
        "benchmark_silver": silver_bench,
        "wholesale_gold_1kg": wholesale_1kg,
        "city_tape": city_tape,
        "parity": parity_info,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "timestamp_ist": datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p IST"),
    }


def get_bullion_history(
    city_code: str | None = None,
    product_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Retrieve historical observations for charting and auditing."""
    db = SessionLocal()
    try:
        stmt = select(BullionRateObservation).order_by(desc(BullionRateObservation.observed_at))
        if city_code:
            norm_code = normalize_city_code(city_code)
            stmt = stmt.where(BullionRateObservation.city_code == norm_code)
        if product_id:
            stmt = stmt.where(BullionRateObservation.product_id == product_id)

        stmt = stmt.offset(offset).limit(min(limit, 1000))
        results = db.execute(stmt).scalars().all()
        if results:
            return [
                {
                    "id": obs.id,
                    "city_code": obs.city_code,
                    "product_id": obs.product_id,
                    "price": obs.price,
                    "currency": obs.currency,
                    "rate_type": obs.rate_type,
                    "unit": obs.unit,
                    "source_url": obs.source_url,
                    "source_published_at": obs.source_published_at.isoformat() if obs.source_published_at else None,
                    "observed_at": obs.observed_at.isoformat(),
                    "is_changed": obs.is_changed,
                    "freshness_status": obs.freshness_status,
                }
                for obs in results
            ]
    except Exception:
        pass
    finally:
        db.close()

    # CSV fallback
    if CITY_RATES_CSV.exists():
        records = []
        with CITY_RATES_CSV.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            if city_code:
                norm_code = normalize_city_code(city_code)
                reader = [r for r in reader if r["city_code"] == norm_code]
            if product_id:
                reader = [r for r in reader if r["product_id"] == product_id]

            sliced = reader[-(offset + limit):len(reader) - offset] if offset < len(reader) else []
            sliced.reverse()
            for idx, r in enumerate(sliced):
                records.append({
                    "id": idx + 1,
                    "city_code": r["city_code"],
                    "product_id": r["product_id"],
                    "price": float(r["price"]),
                    "currency": r.get("currency", "INR"),
                    "rate_type": r.get("rate_type", "RETAIL"),
                    "unit": r.get("unit", "100g"),
                    "source_url": r.get("source", "http://www.kjpl.in/"),
                    "source_published_at": None,
                    "observed_at": r["observed_at"],
                    "is_changed": True,
                    "freshness_status": "FRESH",
                })
        return records
    return []


def get_data_monitor_status() -> dict[str, Any]:
    """Inspect collector status, database connection, and data freshness."""
    is_prod = os.environ.get("ENVIRONMENT", "development").lower() == "production"
    db_mode = "PostgreSQL (Production)" if IS_POSTGRES else "SQLite (Local Development Fallback)"

    # Probe DB connection
    db_ok = False
    db = SessionLocal()
    try:
        db.execute(select(1)).scalar()
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()

    # Fetch last collector runs
    collectors = []
    db = SessionLocal()
    try:
        runs = db.execute(select(CollectorRun).order_by(desc(CollectorRun.executed_at)).limit(10)).scalars().all()
        for r in runs:
            collectors.append({
                "collector_name": r.collector_name,
                "status": r.status,
                "records_extracted": r.records_extracted,
                "records_inserted": r.records_inserted,
                "records_changed": r.records_changed,
                "duration_seconds": r.duration_seconds,
                "executed_at": r.executed_at.isoformat(),
                "error_message": r.error_message,
            })
    except Exception:
        pass
    finally:
        db.close()

    # City freshness check
    all_rates = get_latest_city_rates()
    city_freshness: dict[str, Any] = {}
    for c in ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]:
        entry = next((r for r in all_rates if r["city_code"] == c and r["product_id"] == "GOLD_100G_999"), None)
        if entry:
            city_freshness[c] = {
                "freshness": entry["freshness"],
                "age_hours": entry["age_hours"],
                "age_display": entry["age_display"],
                "source_updated_time": entry["source_updated_time"],
                "last_verified_at": entry["last_verified_at"],
            }
        else:
            city_freshness[c] = {
                "freshness": "UNAVAILABLE",
                "age_hours": 999.0,
                "age_display": "No Data",
                "source_updated_time": "N/A",
                "last_verified_at": None,
            }

    return {
        "status": "OPERATIONAL" if db_ok else "DEGRADED",
        "service": "VMD Bullion Intelligence Data Monitor",
        "environment": "production" if is_prod else "development",
        "database": {
            "connected": db_ok,
            "engine": "postgresql" if IS_POSTGRES else "sqlite",
            "description": db_mode,
            "is_production_ready": IS_POSTGRES,
        },
        "city_freshness": city_freshness,
        "recent_runs": collectors,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def get_collector_runs_history(limit: int = 50) -> list[dict[str, Any]]:
    """List recent collector executions."""
    db = SessionLocal()
    runs_list = []
    try:
        runs = db.execute(
            select(CollectorRun).order_by(desc(CollectorRun.executed_at)).limit(min(limit, 200))
        ).scalars().all()
        for r in runs:
            runs_list.append({
                "id": r.id,
                "collector_name": r.collector_name,
                "status": r.status,
                "records_extracted": r.records_extracted,
                "records_inserted": r.records_inserted,
                "records_changed": r.records_changed,
                "duration_seconds": r.duration_seconds,
                "executed_at": r.executed_at.isoformat(),
                "error_message": r.error_message,
            })
    except Exception:
        pass
    finally:
        db.close()
    return runs_list
