from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, ENVIRONMENT, IS_POSTGRES, check_database_health
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
    get_market_trading_status,
    TROY_OUNCE_GRAMS,
)
from app.services.kjpl.live_rate_service import live_city_cache, is_non_persistent_city_feed

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CITY_RATES_CSV = Path(os.environ.get("VMD_CITY_RATES_CSV", str(PROJECT_ROOT / "data/kjpl/city_rates.csv")))

MANDATORY_CITIES = [
    {"city_code": "CHENNAI", "display_name": "Chennai", "state": "Tamil Nadu", "sort_order": 1, "is_default": True},
    {"city_code": "BENGALURU", "display_name": "Bengaluru", "state": "Karnataka", "sort_order": 2, "is_default": False},
    {"city_code": "MUMBAI", "display_name": "Mumbai", "state": "Maharashtra", "sort_order": 3, "is_default": False},
    {"city_code": "COIMBATORE", "display_name": "Coimbatore", "state": "Tamil Nadu", "sort_order": 4, "is_default": False},
    {"city_code": "HYDERABAD", "display_name": "Hyderabad", "state": "Telangana", "sort_order": 5, "is_default": False},
    {"city_code": "ALL_INDIA", "display_name": "National", "state": "All India", "sort_order": 6, "is_default": False},
]


def normalize_city_code(city_input: str) -> str:
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


def _format_pub_time_ist(pub_dt: datetime | None) -> str:
    if not pub_dt:
        return "Unverified"
    dt_ist = pub_dt.replace(tzinfo=timezone.utc).astimezone(IST) if pub_dt.tzinfo is None else pub_dt.astimezone(IST)
    return dt_ist.strftime("%d %b %I:%M %p IST")


def _serialize_latest_rate(
    rate_obj: BullionLatestRate,
    prod_obj: BullionProduct,
    city_obj: BullionCity,
    *,
    market_status_str: str | None = None,
    source_unavailable: bool = False,
) -> dict[str, Any]:
    latest_price = float(rate_obj.latest_price)
    if rate_obj.normalized_price_per_gram is not None:
        per_gram = float(rate_obj.normalized_price_per_gram)
    elif rate_obj.currency == "INR" and float(rate_obj.product_weight_grams or 1.0) > 0:
        per_gram = round(latest_price / float(rate_obj.product_weight_grams or 1.0), 2)
    else:
        per_gram = None

    fresh_ref = rate_obj.source_published_at or rate_obj.last_verified_at
    freshness = get_freshness_details(
        fresh_ref,
        rate_type=rate_obj.rate_type,
        market_status_override=market_status_str,
        source_unavailable=source_unavailable,
    )

    return {
        "city_code": city_obj.city_code,
        "city_display_name": city_obj.display_name,
        "product_id": prod_obj.product_id,
        "product_name": prod_obj.product_name,
        "metal": prod_obj.metal,
        "purity": float(prod_obj.purity),
        "weight": float(prod_obj.weight),
        "product_weight_grams": float(rate_obj.product_weight_grams or 1.0),
        "unit": rate_obj.unit,
        "rate_type": rate_obj.rate_type,
        "latest_price": latest_price,
        "buy_price": float(rate_obj.buy_price) if rate_obj.buy_price is not None else None,
        "previous_price": float(rate_obj.previous_price) if rate_obj.previous_price is not None else None,
        "change_inr": float(rate_obj.change_inr),
        "change_pct": float(rate_obj.change_pct),
        "per_gram_price": per_gram,
        "currency": rate_obj.currency,
        "source_product_id": rate_obj.source_product_id or prod_obj.source_product_id,
        "validation_status": rate_obj.validation_status,
        "source_published_at": rate_obj.source_published_at.isoformat() if rate_obj.source_published_at else None,
        "source_updated_time": _format_pub_time_ist(rate_obj.source_published_at),
        "observed_at": rate_obj.last_collected_at.isoformat(),
        "last_verified_at": rate_obj.last_verified_at.isoformat(),
        "freshness": freshness["status"],
        "age_hours": freshness["age_hours"],
        "age_seconds": freshness["age_seconds"],
        "age_display": freshness["age_display"],
        "source_url": rate_obj.source_url,
    }


def get_all_cities(db: Session | None = None) -> list[dict[str, Any]]:
    own = False
    if db is None:
        db = SessionLocal()
        own = True
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
        if ENVIRONMENT == "production":
            raise
    finally:
        if own:
            db.close()

    return MANDATORY_CITIES


def _read_latest_rates_from_csv() -> list[dict[str, Any]]:
    """Local dev CSV fallback only. Strictly disabled when ENVIRONMENT=production."""
    if ENVIRONMENT == "production" or not CITY_RATES_CSV.exists():
        return []

    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    with CITY_RATES_CSV.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            latest_by_key[(row["city_code"], row["product_id"])] = row

    items: list[dict[str, Any]] = []
    for (city, prod), row in latest_by_key.items():
        price = float(row["price"])
        weight = float(row.get("weight", 1.0))
        unit = row.get("unit", "1g")
        wg = 100.0 if unit == "100g" and weight == 100.0 else (1000.0 if unit == "1kg" and weight == 1.0 else weight)
        per_gram = round(price / wg, 2) if wg > 0 else price
        obs_dt = datetime.fromisoformat(row["observed_at"])
        rate_type = row.get("rate_type", "RETAIL")
        freshness = get_freshness_details(obs_dt, rate_type=rate_type)

        items.append({
            "city_code": city,
            "city_display_name": row.get("city_display_name", city),
            "product_id": prod,
            "product_name": row.get("product_name", prod),
            "metal": row.get("metal", "GOLD"),
            "purity": float(row.get("purity", 0.999)),
            "weight": weight,
            "product_weight_grams": wg,
            "unit": unit,
            "rate_type": rate_type,
            "latest_price": price,
            "buy_price": None,
            "previous_price": price,
            "change_inr": 0.0,
            "change_pct": 0.0,
            "per_gram_price": per_gram,
            "currency": row.get("currency", "INR"),
            "validation_status": "VALID",
            "source_published_at": None,
            "source_updated_time": row.get("published_time", "N/A"),
            "observed_at": obs_dt.isoformat(),
            "last_verified_at": obs_dt.isoformat(),
            "freshness": freshness["status"],
            "age_hours": freshness["age_hours"],
            "age_seconds": freshness["age_seconds"],
            "age_display": freshness["age_display"],
            "source_url": "http://www.kjpl.in/",
        })
    return items


def get_latest_city_rates(
    city_code: str | None = None,
    metal: str | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    own = False
    if db is None:
        db = SessionLocal()
        own = True

    trading_status = get_market_trading_status()
    indian_mkt_status = trading_status.get("indian_physical_market")

    result_items: list[dict[str, Any]] = []

    try:
        stmt = (
            select(BullionLatestRate, BullionProduct, BullionCity)
            .join(BullionProduct, BullionLatestRate.product_id == BullionProduct.product_id)
            .join(BullionCity, BullionLatestRate.city_code == BullionCity.city_code)
            .where(BullionLatestRate.validation_status.in_(["VALID", "SUSPECT"]))
            .order_by(BullionCity.sort_order, BullionProduct.metal, BullionProduct.product_name)
        )
        if city_code:
            stmt = stmt.where(BullionLatestRate.city_code == normalize_city_code(city_code))
        if metal:
            stmt = stmt.where(BullionProduct.metal == metal.upper())

        rows = db.execute(stmt).all()
        if rows:
            # Check source health flags
            sources = {
                s.source_name: s.current_status
                for s in db.execute(select(DataSourceStatus)).scalars().all()
            }
            result_items = [
                _serialize_latest_rate(
                    rate_obj,
                    prod_obj,
                    city_obj,
                    market_status_str=indian_mkt_status if indian_mkt_status == "SUNDAY_CLOSED" else None,
                    source_unavailable=(
                        sources.get("KJPL_MJDTA" if rate_obj.rate_type == "MJDTA_BENCHMARK" else "KJPL_LIVE") == "DOWN"
                    ),
                )
                for rate_obj, prod_obj, city_obj in rows
            ]
    except Exception:
        if ENVIRONMENT == "production":
            raise
    finally:
        if own:
            db.close()

    # Overlay / merge in-memory cached rates for the five non-persistent city feeds (IDs 48-52)
    cached_cities = live_city_cache.get_all_rates()
    if cached_cities:
        cached_by_city = {c["city_code"]: c for c in cached_cities}
        seen_cities: set[str] = set()
        merged_items: list[dict[str, Any]] = []
        for item in result_items:
            c_code = item["city_code"]
            p_id = item["product_id"]
            sp_id = str(item.get("source_product_id") or "")
            if is_non_persistent_city_feed(sp_id, c_code, p_id) and c_code in cached_by_city:
                merged_items.append(cached_by_city[c_code])
                seen_cities.add(c_code)
            else:
                merged_items.append(item)

        # Append any cached city not present in DB results
        for c_code, cached_item in cached_by_city.items():
            if c_code not in seen_cities:
                match_city = (not city_code or normalize_city_code(city_code) == c_code)
                match_metal = (not metal or metal.upper() == cached_item.get("metal", "GOLD"))
                if match_city and match_metal:
                    merged_items.append(cached_item)

        result_items = merged_items

    if not result_items and ENVIRONMENT != "production":
        csv_rates = _read_latest_rates_from_csv()
        if city_code:
            norm = normalize_city_code(city_code)
            csv_rates = [r for r in csv_rates if r["city_code"] == norm]
        if metal:
            csv_rates = [r for r in csv_rates if r["metal"] == metal.upper()]
        return csv_rates

    return result_items


def get_city_comparison(all_rates: list[dict[str, Any]] | None = None, db: Session | None = None) -> dict[str, Any]:
    """
    Produce verified 5-city comparative matrix for comparable 999 gold city products (`GOLD_100G_999`).
    Compares on normalized INR/gram basis and preserves exact source timestamps and freshness per city.
    """
    if all_rates is None:
        all_rates = get_latest_city_rates(db=db)

    target_cities = ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]
    city_map: dict[str, dict[str, Any]] = {}
    source_id_by_city = {
        "CHENNAI": "48",
        "BENGALURU": "49",
        "MUMBAI": "50",
        "COIMBATORE": "51",
        "HYDERABAD": "52",
    }
    for r in all_rates:
        if (
            r["product_id"] == "GOLD_100G_999"
            and r["city_code"] in target_cities
            and r.get("validation_status") != "QUARANTINED"
            and r.get("per_gram_price")
            and 5000.0 <= float(r["per_gram_price"]) <= 50000.0
        ):
            city_map[r["city_code"]] = r

    chennai_entry = city_map.get("CHENNAI")
    chennai_per_gram = float(chennai_entry["per_gram_price"]) if (chennai_entry and chennai_entry.get("per_gram_price")) else 0.0

    comparison_items: list[dict[str, Any]] = []
    for code in target_cities:
        entry = city_map.get(code)
        if entry and entry.get("per_gram_price"):
            per_gram = float(entry["per_gram_price"])
            diff_inr = round(per_gram - chennai_per_gram, 2) if chennai_per_gram > 0 else 0.0
            diff_pct = round((diff_inr / chennai_per_gram) * 100, 3) if chennai_per_gram > 0 else 0.0
            diff_bps = round((diff_inr / chennai_per_gram) * 10000, 1) if chennai_per_gram > 0 else 0.0
            comparison_items.append({
                "city_code": code,
                "city_display_name": entry["city_display_name"],
                "product_id": entry["product_id"],
                "source_product_id": entry.get("source_product_id") or source_id_by_city[code],
                "purity": entry["purity"],
                "unit": entry["unit"],
                "total_price_100g": round(per_gram * 100.0, 2),
                "per_gram_price": per_gram,
                "spread_vs_chennai_inr": diff_inr,
                "spread_vs_chennai_pct": diff_pct,
                "spread_vs_chennai_bps": diff_bps,
                "is_baseline": (code == "CHENNAI"),
                "validation_status": entry.get("validation_status", "VALID"),
                "source_published_at": entry.get("source_published_at"),
                "source_updated_time": entry["source_updated_time"],
                "observed_at": entry["observed_at"],
                "last_verified_at": entry["last_verified_at"],
                "freshness": entry["freshness"],
            })
        else:
            display_name = next((c["display_name"] for c in MANDATORY_CITIES if c["city_code"] == code), code)
            comparison_items.append({
                "city_code": code,
                "city_display_name": display_name,
                "product_id": "GOLD_100G_999",
                "source_product_id": source_id_by_city[code],
                "purity": 0.999,
                "unit": "1g",
                "total_price_100g": None,
                "per_gram_price": None,
                "spread_vs_chennai_inr": None,
                "spread_vs_chennai_pct": None,
                "spread_vs_chennai_bps": None,
                "is_baseline": (code == "CHENNAI"),
                "validation_status": "SOURCE_UNAVAILABLE",
                "source_published_at": None,
                "source_updated_time": "Unavailable",
                "observed_at": None,
                "last_verified_at": None,
                "freshness": "SOURCE_UNAVAILABLE",
            })

    return {
        "benchmark_city": "CHENNAI",
        "benchmark_per_gram": chennai_per_gram,
        "product_id": "GOLD_100G_999",
        "product_name": "KJPL Gold 100 GMS 999 City Benchmark (IDs 48-52, Quoted INR/1g; 100g Display Equiv)",
        "cities": comparison_items,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_bullion_summary(all_rates: list[dict[str, Any]] | None = None, db: Session | None = None) -> dict[str, Any]:
    """
    Top-level VMD Bullion summary strictly from KJPL verified rates.
    Uses KJPL Type 1/2 benchmarks only; never substitutes external Yahoo/MCX APIs or outdated hardcoded duty %s.
    """
    if all_rates is None:
        all_rates = get_latest_city_rates(db=db)

    chennai_mjdta = next((r for r in all_rates if r["city_code"] == "CHENNAI" and r["product_id"] == "MJDTA_GOLD_24K"), None)
    chennai_mjdta_gst = next((r for r in all_rates if r["city_code"] == "CHENNAI" and r["product_id"] == "MJDTA_GOLD_24K_GST"), None)
    silver_bench = next((r for r in all_rates if r["product_id"] == "MJDTA_SILVER"), None)
    wholesale_1kg = next((r for r in all_rates if r["product_id"] == "GOLD_1KG_9999"), None)

    spot_gold = next((r for r in all_rates if r["product_id"] == "KJPL_SPOT_GOLD_USD"), None)
    spot_silver = next((r for r in all_rates if r["product_id"] == "KJPL_SPOT_SILVER_USD"), None)
    spot_inr = next((r for r in all_rates if r["product_id"] == "KJPL_SPOT_USDINR"), None)
    mcx_gold_contract = next((r for r in all_rates if r["product_id"] == "KJPL_GOLDDEC_INR_10G"), None)
    mcx_silver_contract = next((r for r in all_rates if r["product_id"] == "KJPL_SILVERDEC_INR_1KG"), None)
    lbma_gold_am = next((r for r in all_rates if r["product_id"] == "LBMA_GOLD_AM_USD"), None)
    lbma_gold_pm = next((r for r in all_rates if r["product_id"] == "LBMA_GOLD_PM_USD"), None)
    lbma_silver = next((r for r in all_rates if r["product_id"] == "LBMA_SILVER_USD"), None)

    target_cities = ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]
    city_tape = []
    for c in target_cities:
        entry = next(
            (
                r for r in all_rates
                if r["city_code"] == c
                and r["product_id"] == "GOLD_100G_999"
                and r.get("validation_status") != "QUARANTINED"
                and r.get("per_gram_price")
                and 5000.0 <= float(r["per_gram_price"]) <= 50000.0
            ),
            None,
        )
        if entry and entry.get("per_gram_price"):
            pg = float(entry["per_gram_price"])
            city_tape.append({
                "city_code": entry["city_code"],
                "city_name": entry["city_display_name"],
                "source_product_id": entry.get("source_product_id"),
                "unit": entry.get("unit", "1g"),
                "price_100g": round(pg * 100.0, 2),
                "per_gram": pg,
                "change_inr": entry["change_inr"],
                "change_pct": entry["change_pct"],
                "validation_status": entry.get("validation_status", "VALID"),
                "source_published_at": entry.get("source_published_at"),
                "source_updated_time": entry["source_updated_time"],
                "freshness": entry["freshness"],
            })

    parity_info = None
    if spot_gold and spot_inr:
        xau = float(spot_gold["latest_price"])
        usdinr = float(spot_inr["latest_price"])
        xag = float(spot_silver["latest_price"]) if spot_silver else None
        raw_spot_inr_g = round((xau * usdinr) / TROY_OUNCE_GRAMS, 2)
        ref_gold = chennai_mjdta["per_gram_price"] if chennai_mjdta else None
        spread_vs_spot_inr = round(ref_gold - raw_spot_inr_g, 2) if (ref_gold and raw_spot_inr_g > 0) else None
        spread_vs_spot_pct = round((spread_vs_spot_inr / raw_spot_inr_g) * 100, 2) if (spread_vs_spot_inr is not None and raw_spot_inr_g > 0) else None

        parity_info = {
            "source": "KJPL Live Feed (SPOT-GOLD / SPOT-SILVER / SPOT-INR)",
            "xauusd": xau,
            "xagusd": xag,
            "usdinr": usdinr,
            "raw_spot_inr_per_gram": raw_spot_inr_g,
            "domestic_vs_spot_spread_inr": spread_vs_spot_inr,
            "domestic_vs_spot_spread_pct": spread_vs_spot_pct,
            "market_freshness": spot_gold["freshness"],
            "note": "Raw spot conversion excludes unverified customs/GST policy assumptions.",
        }

    return {
        "terminal_title": "VMD Bullion Intelligence Terminal",
        "default_city": "CHENNAI",
        "data_source": "KJPL Exclusive",
        "trading_status": get_market_trading_status(),
        "benchmark_gold_24k": chennai_mjdta,
        "benchmark_gold_24k_gst": chennai_mjdta_gst,
        "benchmark_silver": silver_bench,
        "wholesale_gold_1kg": wholesale_1kg,
        "kjpl_live_terminal": {
            "spot_gold_usd": spot_gold,
            "spot_silver_usd": spot_silver,
            "spot_usdinr": spot_inr,
            "gold_contract_10g": mcx_gold_contract,
            "silver_contract_1kg": mcx_silver_contract,
            "lbma_gold_am_usd": lbma_gold_am,
            "lbma_gold_pm_usd": lbma_gold_pm,
            "lbma_silver_usd": lbma_silver,
        },
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
    include_quarantined: bool = False,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """Retrieve historical observations strictly excluding QUARANTINED/INVALIDATED rows by default."""
    own = False
    if db is None:
        db = SessionLocal()
        own = True

    try:
        stmt = select(BullionRateObservation).order_by(desc(BullionRateObservation.observed_at))
        if not include_quarantined:
            stmt = stmt.where(BullionRateObservation.validation_status.in_(["VALID", "SUSPECT"]))
        if city_code:
            stmt = stmt.where(BullionRateObservation.city_code == normalize_city_code(city_code))
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
                    "price": float(obs.price),
                    "normalized_price_per_gram": float(obs.normalized_price_per_gram) if obs.normalized_price_per_gram is not None else None,
                    "currency": obs.currency,
                    "rate_type": obs.rate_type,
                    "unit": obs.unit,
                    "validation_status": obs.validation_status,
                    "source_url": obs.source_url,
                    "source_published_at": obs.source_published_at.isoformat() if obs.source_published_at else None,
                    "observed_at": obs.observed_at.isoformat(),
                    "is_changed": obs.is_changed,
                    "freshness_status": obs.freshness_status,
                }
                for obs in results
            ]
    except Exception:
        if ENVIRONMENT == "production":
            raise
    finally:
        if own:
            db.close()

    if ENVIRONMENT == "production" or not CITY_RATES_CSV.exists():
        return []

    records = []
    with CITY_RATES_CSV.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        if city_code:
            norm = normalize_city_code(city_code)
            reader = [r for r in reader if r["city_code"] == norm]
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
                "normalized_price_per_gram": float(r["price"]),
                "currency": r.get("currency", "INR"),
                "rate_type": r.get("rate_type", "RETAIL"),
                "unit": r.get("unit", "1g"),
                "validation_status": "VALID",
                "source_url": "http://www.kjpl.in/",
                "source_published_at": None,
                "observed_at": r["observed_at"],
                "is_changed": True,
                "freshness_status": "FRESH",
            })
    return records


def get_data_monitor_status(all_rates: list[dict[str, Any]] | None = None, db: Session | None = None) -> dict[str, Any]:
    """Single-session health, quarantine metrics, and pipeline freshness monitor."""
    is_prod = ENVIRONMENT == "production"
    db_health = check_database_health()
    db_ok = bool(db_health.get("connected"))
    db_mode = "Neon PostgreSQL (Production)" if db_health.get("is_postgres") else "SQLite (Local Development)"

    collectors = []
    quarantined_count = 0
    valid_count = 0
    source_statuses: list[dict[str, Any]] = []

    if db_ok:
        own = False
        if db is None:
            db = SessionLocal()
            own = True
        try:
            runs = db.execute(select(CollectorRun).order_by(desc(CollectorRun.executed_at)).limit(15)).scalars().all()
            collectors = [
                {
                    "collector_name": r.collector_name,
                    "run_id": r.run_id,
                    "status": r.status,
                    "records_extracted": r.records_extracted,
                    "records_inserted": r.records_inserted,
                    "records_changed": r.records_changed,
                    "records_quarantined": r.records_quarantined,
                    "duration_seconds": r.duration_seconds,
                    "executed_at": r.executed_at.isoformat(),
                    "error_message": r.error_message,
                }
                for r in runs
            ]
            sources = db.execute(select(DataSourceStatus)).scalars().all()
            source_statuses = [
                {
                    "source_name": s.source_name,
                    "current_status": s.current_status,
                    "last_successful_run": s.last_successful_run.isoformat() if s.last_successful_run else None,
                    "last_failed_run": s.last_failed_run.isoformat() if s.last_failed_run else None,
                    "error_message": s.error_message,
                }
                for s in sources
            ]
            quarantined_count = len(db.execute(
                select(BullionRateObservation.id).where(BullionRateObservation.validation_status == "QUARANTINED")
            ).all())
            valid_count = len(db.execute(
                select(BullionRateObservation.id).where(BullionRateObservation.validation_status.in_(["VALID", "SUSPECT"]))
            ).all())
        except Exception as exc:
            db_ok = False
            db_health["error"] = str(exc)
        finally:
            if own:
                db.close()

    if all_rates is None:
        all_rates = get_latest_city_rates(db=db) if db_ok else []

    city_freshness: dict[str, Any] = {}
    for c in ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]:
        entry = next((r for r in all_rates if r["city_code"] == c and r["product_id"] == "GOLD_100G_999"), None)
        if entry:
            city_freshness[c] = {
                "freshness": entry["freshness"],
                "age_hours": entry["age_hours"],
                "age_display": entry["age_display"],
                "source_published_at": entry.get("source_published_at"),
                "source_updated_time": entry["source_updated_time"],
                "last_verified_at": entry["last_verified_at"],
            }
        else:
            city_freshness[c] = {
                "freshness": "SOURCE_UNAVAILABLE",
                "age_hours": None,
                "age_display": "No live city data",
                "source_published_at": None,
                "source_updated_time": "Unavailable",
                "last_verified_at": None,
            }

    return {
        "status": "OPERATIONAL" if db_ok else "DEGRADED",
        "service": "VMD Bullion Intelligence Data Monitor",
        "environment": "production" if is_prod else "development",
        "database": {
            "connected": db_ok,
            "engine": db_health.get("dialect"),
            "description": db_mode,
            "is_production_ready": bool(db_health.get("is_postgres")),
            "error": db_health.get("error"),
        },
        "data_quality": {
            "valid_observations_count": valid_count,
            "quarantined_observations_count": quarantined_count,
        },
        "source_statuses": source_statuses,
        "city_freshness": city_freshness,
        "recent_runs": collectors,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def get_collector_runs_history(limit: int = 50, db: Session | None = None) -> list[dict[str, Any]]:
    own = False
    if db is None:
        db = SessionLocal()
        own = True
    try:
        runs = db.execute(
            select(CollectorRun).order_by(desc(CollectorRun.executed_at)).limit(min(limit, 200))
        ).scalars().all()
        return [
            {
                "id": r.id,
                "collector_name": r.collector_name,
                "run_id": r.run_id,
                "status": r.status,
                "records_extracted": r.records_extracted,
                "records_inserted": r.records_inserted,
                "records_changed": r.records_changed,
                "records_quarantined": r.records_quarantined,
                "duration_seconds": r.duration_seconds,
                "executed_at": r.executed_at.isoformat(),
                "error_message": r.error_message,
            }
            for r in runs
        ]
    except Exception:
        if ENVIRONMENT == "production":
            raise
        return []
    finally:
        if own:
            db.close()


def get_bullion_dashboard(
    city_code: str = "CHENNAI",
    history_limit: int = 30,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Consolidated dashboard payload reducing 6+ parallel frontend requests into 1 DB session.
    """
    own = False
    if db is None:
        db = SessionLocal()
        own = True
    try:
        cities = get_all_cities(db=db)
        all_rates = get_latest_city_rates(db=db)
        summary = get_bullion_summary(all_rates=all_rates, db=db)
        comparison = get_city_comparison(all_rates=all_rates, db=db)
        monitor = get_data_monitor_status(all_rates=all_rates, db=db)
        history = get_bullion_history(city_code=city_code, limit=history_limit, db=db)
        return {
            "summary": summary,
            "cities": cities,
            "city_rates": all_rates,
            "comparison": comparison,
            "monitor": monitor,
            "history": history,
        }
    finally:
        if own:
            db.close()
