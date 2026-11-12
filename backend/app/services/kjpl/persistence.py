from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError

import app.db.session as db_session
from app.db.session import ENVIRONMENT
from app.models.bullion import (
    BullionCity,
    BullionProduct,
    BullionRateObservation,
    BullionLatestRate,
    DataSourceStatus,
)
from app.services.kjpl.city_schemas import ParsedKJPLPayload, ParsedCityRate
from app.services.kjpl.parser import parse_full_kjpl_datetime, resolve_clock_only_kjpl_timestamp
from app.services.kjpl.validator import validate_bullion_observation

IST = ZoneInfo("Asia/Kolkata")
# Never set source_published_at > observed_at for any VALID MJDTA observation (A3-FINAL-4).
MJDTA_FUTURE_TOLERANCE = timedelta(0)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
CITY_RATES_CSV = Path(os.environ.get("VMD_CITY_RATES_CSV", str(PROJECT_ROOT / "data/kjpl/city_rates.csv")))
KJPL_RATES_CSV = Path(os.environ.get("VMD_KJPL_RATES_CSV", str(PROJECT_ROOT / "data/kjpl/kjpl_rates.csv")))

DEFAULT_CITIES = [
    {"city_code": "CHENNAI", "display_name": "Chennai", "state": "Tamil Nadu", "sort_order": 1},
    {"city_code": "BENGALURU", "display_name": "Bengaluru", "state": "Karnataka", "sort_order": 2},
    {"city_code": "MUMBAI", "display_name": "Mumbai", "state": "Maharashtra", "sort_order": 3},
    {"city_code": "COIMBATORE", "display_name": "Coimbatore", "state": "Tamil Nadu", "sort_order": 4},
    {"city_code": "HYDERABAD", "display_name": "Hyderabad", "state": "Telangana", "sort_order": 5},
    {"city_code": "ALL_INDIA", "display_name": "National", "state": "All India", "sort_order": 6},
]

DEFAULT_PRODUCTS = [
    {"product_id": "GOLD_100G_999", "product_name": "KJPL Gold 100 GMS 999 City Benchmark (Quoted 1g)", "metal": "GOLD", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "1g", "rate_type": "RETAIL", "source_product_id": "48-52"},
    {"product_id": "GOLD_1KG_9999", "product_name": "KJPL Gold 1KG 99.99 Pure Bar (Quoted 1g)", "metal": "GOLD", "purity": Decimal("0.9999"), "weight": Decimal("1.0000"), "unit": "1g", "rate_type": "WHOLESALE", "source_product_id": "47"},
    {"product_id": "MJDTA_GOLD_24K", "product_name": "MJDTA Gold 24K Benchmark (Excl. GST)", "metal": "GOLD", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "1g", "rate_type": "MJDTA_BENCHMARK", "source_product_id": "MJDTA_GOLD"},
    {"product_id": "MJDTA_GOLD_24K_GST", "product_name": "MJDTA Gold 24K Benchmark (With 3% GST)", "metal": "GOLD", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "1g", "rate_type": "MJDTA_BENCHMARK", "source_product_id": "MJDTA_GOLD_GST"},
    {"product_id": "MJDTA_SILVER", "product_name": "MJDTA Silver Benchmark (Excl. GST)", "metal": "SILVER", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "1g", "rate_type": "MJDTA_BENCHMARK", "source_product_id": "2"},
    {"product_id": "SILVER_1KG_999", "product_name": "Silver 1KG 999 Bar", "metal": "SILVER", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "1kg", "rate_type": "RETAIL", "source_product_id": "12"},
    {"product_id": "KJPL_GOLDDEC_INR_10G", "product_name": "KJPL Gold Contract (10g)", "metal": "GOLD", "purity": Decimal("0.9950"), "weight": Decimal("10.0000"), "unit": "10g", "rate_type": "KJPL_LIVE", "source_product_id": "GOLDDEC"},
    {"product_id": "KJPL_SILVERDEC_INR_1KG", "product_name": "KJPL Silver Contract (1kg)", "metal": "SILVER", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "1kg", "rate_type": "KJPL_LIVE", "source_product_id": "SILVERDEC"},
    {"product_id": "KJPL_SPOT_GOLD_USD", "product_name": "KJPL Spot Gold ($/oz)", "metal": "GOLD", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "oz", "rate_type": "KJPL_LIVE", "source_product_id": "SPOT-GOLD"},
    {"product_id": "KJPL_SPOT_SILVER_USD", "product_name": "KJPL Spot Silver ($/oz)", "metal": "SILVER", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "oz", "rate_type": "KJPL_LIVE", "source_product_id": "SPOT-SILVER"},
    {"product_id": "KJPL_SPOT_USDINR", "product_name": "KJPL Spot USD/INR", "metal": "FX", "purity": Decimal("1.0000"), "weight": Decimal("1.0000"), "unit": "USD", "rate_type": "KJPL_LIVE", "source_product_id": "SPOT-INR"},
    {"product_id": "LBMA_GOLD_AM_USD", "product_name": "LBMA London Gold AM Fix ($/oz)", "metal": "GOLD", "purity": Decimal("0.9950"), "weight": Decimal("1.0000"), "unit": "oz", "rate_type": "LBMA_FIX", "source_product_id": "LBMA_GOLD_AM"},
    {"product_id": "LBMA_GOLD_PM_USD", "product_name": "LBMA London Gold PM Fix ($/oz)", "metal": "GOLD", "purity": Decimal("0.9950"), "weight": Decimal("1.0000"), "unit": "oz", "rate_type": "LBMA_FIX", "source_product_id": "LBMA_GOLD_PM"},
    {"product_id": "LBMA_SILVER_USD", "product_name": "LBMA London Silver Fix ($/oz)", "metal": "SILVER", "purity": Decimal("0.9990"), "weight": Decimal("1.0000"), "unit": "oz", "rate_type": "LBMA_FIX", "source_product_id": "LBMA_SILVER"},
]


def _to_dec(val: float | Decimal | None, places: str = "0.01") -> Decimal | None:
    if val is None:
        return None
    return Decimal(str(val)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def seed_bullion_metadata(session: Any = None, *, ensure_schema: bool = False) -> None:
    """
    Idempotently seed mandatory cities, standardized KJPL products, and data source status entries.
    """
    own_session = False
    if session is None:
        session = db_session.SessionLocal()
        own_session = True

    if ensure_schema:
        try:
            from app.db.base import Base
            import app.models  # noqa: F401
            bind_engine = session.get_bind()
            Base.metadata.create_all(bind=bind_engine)
        except Exception as e:
            print(f"[METADATA SEED] Schema create notice: {e}")

    try:
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
                    source_product_id=p.get("source_product_id"),
                    is_active=True,
                ))
            else:
                # Repair legacy prototype metadata only if any field actually differs (runtime role has SELECT-only on metadata)
                if (
                    existing.product_name != p["product_name"]
                    or existing.metal != p["metal"]
                    or existing.purity != p["purity"]
                    or existing.weight != p["weight"]
                    or existing.unit != p["unit"]
                    or existing.rate_type != p["rate_type"]
                    or existing.source_product_id != p.get("source_product_id")
                ):
                    existing.product_name = p["product_name"]
                    existing.metal = p["metal"]
                    existing.purity = p["purity"]
                    existing.weight = p["weight"]
                    existing.unit = p["unit"]
                    existing.rate_type = p["rate_type"]
                    existing.source_product_id = p.get("source_product_id")

        for source_key in ("KJPL_MJDTA", "KJPL_LIVE", "KJPL"):
            ds = session.execute(
                select(DataSourceStatus).where(DataSourceStatus.source_name == source_key)
            ).scalar_one_or_none()
            if not ds:
                session.add(DataSourceStatus(
                    source_name=source_key,
                    current_status="OPERATIONAL",
                    updated_at=datetime.now(timezone.utc),
                ))

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def persist_parsed_payload(
    payload: ParsedKJPLPayload,
    source_url: str = "http://www.kjpl.in/",
    session: Any = None,
    *,
    source_key: str = "KJPL_MJDTA",
    mirror_csv: bool | None = None,
    csv_path: Path | None = None,
) -> dict[str, Any]:
    """
    Persist validated KJPL observations with Decimal precision and strict quarantine rules:
      1. Quarantined items are recorded in bullion_rate_observations with validation_status='QUARANTINED'
         and NEVER update bullion_latest_rates.
      2. Valid items update bullion_latest_rates only if changed (or bump last_verified_at if unchanged)
         and append only changed/new valid observations to bullion_rate_observations.
      3. In production, DB failures raise explicitly (never hidden via silent CSV fallback).
    """
    own_session = False
    if session is None:
        session = db_session.SessionLocal()
        own_session = True

    is_dev = ENVIRONMENT != "production"
    should_mirror = is_dev if mirror_csv is None else mirror_csv
    target_csv = csv_path or CITY_RATES_CSV

    seed_bullion_metadata(session, ensure_schema=(session.get_bind().dialect.name == "sqlite"))

    inserted_count = 0
    changed_count = 0
    quarantined_count = 0
    now_utc = datetime.now(timezone.utc)
    source_pub_utc = (
        payload.source_updated_at.astimezone(timezone.utc)
        if payload.source_updated_at is not None
        else None
    )
    csv_rows_to_append: list[dict[str, Any]] = []
    item_logs: list[dict[str, Any]] = []

    try:
        # 1. Log any items already quarantined by parser
        for q_rate in payload.quarantined_rates:
            quarantined_count += 1
            item_logs.append({
                "source_product_id": q_rate.source_product_id or q_rate.product_id,
                "city": q_rate.city_code,
                "product_id": q_rate.product_id,
                "raw_value": q_rate.price,
                "raw_unit": q_rate.unit,
                "normalized_value": q_rate.normalized_price_per_gram,
                "normalized_unit": "INR/g" if q_rate.currency == "INR" else f"{q_rate.currency}/{q_rate.unit}",
                "validation_status": "QUARANTINED",
                "persistence_result": f"QUARANTINED: {q_rate.quarantine_reason or 'Validation rejected'}",
            })
            session.add(BullionRateObservation(
                city_code=q_rate.city_code,
                product_id=q_rate.product_id,
                price=_to_dec(q_rate.price),
                buy_price=_to_dec(q_rate.buy_price),
                currency=q_rate.currency,
                rate_type=q_rate.rate_type,
                unit=q_rate.unit,
                source_name=q_rate.source_name,
                source_product_id=q_rate.source_product_id,
                raw_source_name=q_rate.raw_source_name,
                product_weight_grams=_to_dec(q_rate.product_weight_grams, "0.0001") or Decimal("1.0000"),
                original_price=_to_dec(q_rate.price),
                original_unit=q_rate.unit,
                normalized_price_per_gram=_to_dec(q_rate.normalized_price_per_gram),
                source_url=source_url,
                source_published_at=source_pub_utc,
                observed_at=now_utc,
                is_changed=False,
                freshness_status="QUARANTINED",
                validation_status="QUARANTINED",
                quarantine_reason=q_rate.quarantine_reason,
                raw_payload_reference=q_rate.raw_payload_reference,
            ))

        # 2. Process valid/parsed rates
        raw_src_time = (payload.source_updated_time or "")[:64] or None
        prec_mode = _timestamp_precision(payload)
        is_clock_only = prec_mode in {"CLOCK_ONLY", "INFERRED_CLOCK_ONLY", "AMBIGUOUS_CLOCK_ONLY"}
        norm_prec_label = (
            "INFERRED_CLOCK_ONLY"
            if prec_mode in {"CLOCK_ONLY", "INFERRED_CLOCK_ONLY"}
            else (prec_mode or ("MISSING" if source_pub_utc is None else "FULL"))
        )

        for rate in payload.city_rates:
            # NEW-2 / A3-FINAL-4: MJDTA benchmarks must carry a verified, non-future source publication timestamp.
            mjdta_reason: str | None = None
            quarantined_prec = norm_prec_label
            quarantined_pub = source_pub_utc
            if rate.rate_type == "MJDTA_BENCHMARK":
                if source_pub_utc is None:
                    quarantined_pub = None
                    if prec_mode == "AMBIGUOUS_CLOCK_ONLY" or (raw_src_time and parse_full_kjpl_datetime(raw_src_time) is None):
                        quarantined_prec = "AMBIGUOUS_CLOCK_ONLY"
                        mjdta_reason = (
                            f"Ambiguous clock-only source_published_at ({raw_src_time}); "
                            "cannot establish publication date without guessing"
                        )
                    else:
                        quarantined_prec = "MISSING"
                        mjdta_reason = "Missing genuine source_published_at timestamp for MJDTA publication"
                elif source_pub_utc > now_utc + MJDTA_FUTURE_TOLERANCE:
                    # Never set source_published_at > observed_at for a VALID observation.
                    quarantined_pub = None
                    mjdta_reason = (
                        "Future source_published_at for MJDTA publication "
                        f"({source_pub_utc.isoformat()} > observed {now_utc.isoformat()})"
                    )
                elif is_clock_only and raw_src_time:
                    clk_check = resolve_clock_only_kjpl_timestamp(raw_src_time, now_utc.astimezone(IST))
                    if clk_check.is_pre_open_carryover:
                        prior_match = session.execute(
                            select(BullionRateObservation)
                            .where(
                                BullionRateObservation.city_code == rate.city_code,
                                BullionRateObservation.product_id == rate.product_id,
                                BullionRateObservation.source_product_id == rate.source_product_id,
                                BullionRateObservation.source_published_at == source_pub_utc,
                                BullionRateObservation.validation_status == "VALID",
                            )
                            .order_by(BullionRateObservation.revision_number.desc(), BullionRateObservation.id.desc())
                            .limit(1)
                        ).scalar_one_or_none()
                        if prior_match is None or abs(Decimal(str(prior_match.price)) - _to_dec(rate.price)) > Decimal("0.001"):
                            quarantined_pub = None
                            quarantined_prec = "AMBIGUOUS_CLOCK_ONLY"
                            mjdta_reason = (
                                f"Unverified pre-open clock-only timestamp ({raw_src_time}); "
                                "no matching prior publication carryover evidence"
                            )

            if mjdta_reason is not None:
                quarantined_count += 1
                reason = mjdta_reason
                item_logs.append({
                    "source_product_id": rate.source_product_id or rate.product_id,
                    "city": rate.city_code,
                    "product_id": rate.product_id,
                    "raw_value": rate.price,
                    "raw_unit": rate.unit,
                    "normalized_value": rate.normalized_price_per_gram,
                    "normalized_unit": "INR/g" if rate.currency == "INR" else f"{rate.currency}/{rate.unit}",
                    "validation_status": "QUARANTINED",
                    "persistence_result": f"QUARANTINED: {reason}",
                })
                session.add(BullionRateObservation(
                    city_code=rate.city_code,
                    product_id=rate.product_id,
                    price=_to_dec(rate.price),
                    buy_price=_to_dec(rate.buy_price),
                    currency=rate.currency,
                    rate_type=rate.rate_type,
                    unit=rate.unit,
                    source_name=rate.source_name,
                    source_product_id=rate.source_product_id,
                    raw_source_name=rate.raw_source_name,
                    product_weight_grams=_to_dec(rate.product_weight_grams, "0.0001") or Decimal("1.0000"),
                    original_price=_to_dec(rate.price),
                    original_unit=rate.unit,
                    normalized_price_per_gram=_to_dec(rate.normalized_price_per_gram),
                    source_url=source_url,
                    source_published_at=quarantined_pub,
                    raw_source_published_time=raw_src_time,
                    source_timestamp_precision=quarantined_prec,
                    is_timestamp_inferred=is_clock_only,
                    observed_at=now_utc,
                    observation_kind="ORIGINAL",
                    revision_number=1,
                    is_changed=False,
                    freshness_status="QUARANTINED",
                    validation_status="QUARANTINED",
                    quarantine_reason=reason,
                    raw_payload_reference=rate.raw_payload_reference,
                ))
                continue

            stmt = select(BullionLatestRate).where(
                BullionLatestRate.city_code == rate.city_code,
                BullionLatestRate.product_id == rate.product_id,
            )
            latest_record = session.execute(stmt).scalar_one_or_none()

            prev_norm_per_gram = (
                float(latest_record.normalized_price_per_gram)
                if (latest_record and latest_record.normalized_price_per_gram is not None)
                else None
            )
            outcome = validate_bullion_observation(
                product_id=rate.product_id,
                metal=rate.metal,
                currency=rate.currency,
                unit=rate.unit,
                weight_value=rate.weight,
                price=rate.price,
                source_product_id=rate.source_product_id,
                previous_valid_per_gram=prev_norm_per_gram,
            )

            if outcome.validation_status in ("QUARANTINED", "INVALIDATED"):
                quarantined_count += 1
                item_logs.append({
                    "source_product_id": rate.source_product_id or rate.product_id,
                    "city": rate.city_code,
                    "product_id": rate.product_id,
                    "raw_value": rate.price,
                    "raw_unit": rate.unit,
                    "normalized_value": outcome.normalized_price_per_gram,
                    "normalized_unit": "INR/g" if rate.currency == "INR" else f"{rate.currency}/{rate.unit}",
                    "validation_status": outcome.validation_status,
                    "persistence_result": f"QUARANTINED: {outcome.reason or 'Validation rejected'}",
                })
                session.add(BullionRateObservation(
                    city_code=rate.city_code,
                    product_id=rate.product_id,
                    price=_to_dec(rate.price),
                    buy_price=_to_dec(rate.buy_price),
                    currency=rate.currency,
                    rate_type=rate.rate_type,
                    unit=rate.unit,
                    source_name=rate.source_name,
                    source_product_id=rate.source_product_id,
                    raw_source_name=rate.raw_source_name,
                    product_weight_grams=_to_dec(outcome.product_weight_grams, "0.0001") or Decimal("1.0000"),
                    original_price=_to_dec(rate.price),
                    original_unit=rate.unit,
                    normalized_price_per_gram=_to_dec(outcome.normalized_price_per_gram),
                    source_url=source_url,
                    source_published_at=source_pub_utc,
                    observed_at=now_utc,
                    is_changed=False,
                    freshness_status="QUARANTINED",
                    validation_status=outcome.validation_status,
                    quarantine_reason=outcome.reason,
                    raw_payload_reference=rate.raw_payload_reference,
                ))
                continue

            new_price_dec = _to_dec(rate.price)
            buy_price_dec = _to_dec(rate.buy_price)
            norm_per_gram_dec = _to_dec(outcome.normalized_price_per_gram)
            weight_g_dec = _to_dec(outcome.product_weight_grams, "0.0001") or Decimal("1.0000")

            price_changed = False
            if latest_record is None:
                price_changed = True
                latest_record = BullionLatestRate(
                    city_code=rate.city_code,
                    product_id=rate.product_id,
                    latest_price=new_price_dec,
                    buy_price=buy_price_dec,
                    previous_price=new_price_dec,
                    change_inr=Decimal("0.00"),
                    change_pct=Decimal("0.0000"),
                    normalized_price_per_gram=norm_per_gram_dec,
                    product_weight_grams=weight_g_dec,
                    currency=rate.currency,
                    unit=rate.unit,
                    rate_type=rate.rate_type,
                    source_product_id=rate.source_product_id,
                    validation_status=outcome.validation_status,
                    source_published_at=source_pub_utc,
                    last_collected_at=now_utc,
                    last_verified_at=now_utc,
                    freshness_status="FRESH",
                    source_url=source_url,
                )
                session.add(latest_record)
                changed_count += 1
                persistence_action = "INSERTED_LATEST"
            else:
                prev_dec = Decimal(str(latest_record.latest_price))
                if abs(prev_dec - new_price_dec) > Decimal("0.001"):
                    price_changed = True
                    delta_dec = (new_price_dec - prev_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    pct_dec = (
                        ((delta_dec / prev_dec) * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        if prev_dec > Decimal("0")
                        else Decimal("0.0000")
                    )
                    latest_record.previous_price = prev_dec
                    latest_record.latest_price = new_price_dec
                    latest_record.buy_price = buy_price_dec
                    latest_record.change_inr = delta_dec
                    latest_record.change_pct = pct_dec
                    latest_record.normalized_price_per_gram = norm_per_gram_dec
                    latest_record.product_weight_grams = weight_g_dec
                    latest_record.unit = rate.unit
                    latest_record.validation_status = outcome.validation_status
                    latest_record.source_published_at = source_pub_utc or latest_record.source_published_at
                    latest_record.last_collected_at = now_utc
                    changed_count += 1
                    persistence_action = "UPDATED_CHANGED"
                else:
                    # Unchanged: preserve latest_price and previous_price, refresh normalized metadata & verification time
                    latest_record.normalized_price_per_gram = norm_per_gram_dec
                    latest_record.product_weight_grams = weight_g_dec
                    latest_record.unit = rate.unit
                    latest_record.source_product_id = rate.source_product_id or latest_record.source_product_id
                    latest_record.validation_status = outcome.validation_status
                    latest_record.source_published_at = source_pub_utc or latest_record.source_published_at
                    latest_record.last_collected_at = now_utc
                    persistence_action = "VERIFIED_UNCHANGED"

                latest_record.last_verified_at = now_utc
                latest_record.freshness_status = "FRESH"

            norm_unit_label = (
                "INR/USD"
                if rate.metal == "FX"
                else ("INR/g" if rate.currency == "INR" else f"{rate.currency}/{rate.unit}")
            )
            item_logs.append({
                "source_product_id": rate.source_product_id or rate.product_id,
                "city": rate.city_code,
                "product_id": rate.product_id,
                "raw_value": float(new_price_dec),
                "raw_unit": rate.unit,
                "normalized_value": float(norm_per_gram_dec) if norm_per_gram_dec is not None else float(new_price_dec),
                "normalized_unit": norm_unit_label,
                "validation_status": outcome.validation_status,
                "persistence_result": persistence_action,
            })

            is_distinct_new_publication = False
            skip_non_correction_insert = False
            obs_kind = "ORIGINAL"
            obs_rev = 1
            supersedes_id: int | None = None
            corr_reason: str | None = None
            obs_prec_col = norm_prec_label
            obs_inferred_col = is_clock_only

            if rate.rate_type == "MJDTA_BENCHMARK" and source_pub_utc is not None:
                if session.get_bind().dialect.name == "postgresql":
                    lock_key = f"vmd_pub_{rate.city_code}_{rate.product_id}_{rate.source_product_id}_{source_pub_utc.isoformat()}"
                    session.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": lock_key})

                latest_for_pub = session.execute(
                    select(BullionRateObservation)
                    .where(
                        BullionRateObservation.city_code == rate.city_code,
                        BullionRateObservation.product_id == rate.product_id,
                        BullionRateObservation.source_product_id == rate.source_product_id,
                        BullionRateObservation.source_published_at == source_pub_utc,
                        BullionRateObservation.validation_status == "VALID",
                    )
                    .order_by(BullionRateObservation.revision_number.desc(), BullionRateObservation.id.desc())
                    .limit(1)
                ).scalar_one_or_none()

                if latest_for_pub is None:
                    if (
                        is_clock_only
                        and (
                            (not price_changed and _is_clock_only_carryover(session, rate, source_pub_utc))
                            or payload.market_status == "CLOSED"
                        )
                    ):
                        # Uncertain carryover / closed-market repeat: never silently drop, record QUARANTINED diagnostic row.
                        is_distinct_new_publication = False
                        skip_non_correction_insert = True
                        quarantined_count += 1
                        item_logs[-1]["persistence_result"] = "SKIPPED_CLOCK_ONLY_CARRYOVER"
                        item_logs[-1]["validation_status"] = "QUARANTINED"
                        session.add(BullionRateObservation(
                            city_code=rate.city_code,
                            product_id=rate.product_id,
                            price=new_price_dec,
                            buy_price=buy_price_dec,
                            currency=rate.currency,
                            rate_type=rate.rate_type,
                            unit=rate.unit,
                            source_name=rate.source_name,
                            source_product_id=rate.source_product_id,
                            raw_source_name=rate.raw_source_name,
                            product_weight_grams=weight_g_dec,
                            original_price=new_price_dec,
                            original_unit=rate.unit,
                            normalized_price_per_gram=norm_per_gram_dec,
                            source_url=source_url,
                            source_published_at=None,
                            raw_source_published_time=raw_src_time,
                            source_timestamp_precision="INFERRED_CLOCK_ONLY",
                            is_timestamp_inferred=True,
                            observed_at=now_utc,
                            observation_kind="ORIGINAL",
                            revision_number=1,
                            is_changed=False,
                            freshness_status="QUARANTINED",
                            validation_status="QUARANTINED",
                            quarantine_reason=(
                                "Uncertain clock-only carryover or closed-market repeat "
                                f"({raw_src_time or ''}); date not established"
                            ),
                            raw_payload_reference=rate.raw_payload_reference,
                        ))
                    else:
                        is_distinct_new_publication = True
                else:
                    existing_pub_price = Decimal(str(latest_for_pub.price))
                    if abs(existing_pub_price - new_price_dec) <= Decimal("0.001"):
                        # Exact repeat poll or correction replay -> idempotent, insert zero rows
                        is_distinct_new_publication = False
                        skip_non_correction_insert = True
                    else:
                        # A3-FINAL-3: Same-publication price correction -> append linked CORRECTION version
                        is_distinct_new_publication = True
                        obs_kind = "CORRECTION"
                        obs_rev = int(latest_for_pub.revision_number or 1) + 1
                        supersedes_id = latest_for_pub.id
                        corr_reason = (
                            f"Source price corrected from {existing_pub_price} to {new_price_dec} "
                            f"for source_published_at={source_pub_utc.isoformat()}"
                        )
                        item_logs[-1]["persistence_result"] = f"RECORDED_CORRECTION_REV_{obs_rev}"

            should_insert_obs = (not skip_non_correction_insert) and (
                is_distinct_new_publication or (rate.rate_type != "MJDTA_BENCHMARK" and price_changed)
            )
            if should_insert_obs:
                obs_kwargs = dict(
                    city_code=rate.city_code,
                    product_id=rate.product_id,
                    price=new_price_dec,
                    buy_price=buy_price_dec,
                    currency=rate.currency,
                    rate_type=rate.rate_type,
                    unit=rate.unit,
                    source_name=rate.source_name,
                    source_product_id=rate.source_product_id,
                    raw_source_name=rate.raw_source_name,
                    product_weight_grams=weight_g_dec,
                    original_price=new_price_dec,
                    original_unit=rate.unit,
                    normalized_price_per_gram=norm_per_gram_dec,
                    source_url=source_url,
                    source_published_at=source_pub_utc,
                    raw_source_published_time=raw_src_time,
                    source_timestamp_precision=obs_prec_col,
                    is_timestamp_inferred=obs_inferred_col,
                    observed_at=now_utc,
                    observation_kind=obs_kind,
                    revision_number=obs_rev,
                    supersedes_observation_id=supersedes_id,
                    correction_reason=corr_reason,
                    is_changed=(price_changed or obs_kind == "CORRECTION"),
                    freshness_status="FRESH",
                    validation_status=outcome.validation_status,
                    quarantine_reason=outcome.reason,
                    raw_payload_reference=rate.raw_payload_reference,
                )
                try:
                    with session.begin_nested():
                        session.add(BullionRateObservation(**obs_kwargs))
                        session.flush()
                    inserted_count += 1
                except IntegrityError:
                    # Concurrent worker won the exact (source_published_at, revision_number) slot
                    winner = session.execute(
                        select(BullionRateObservation)
                        .where(
                            BullionRateObservation.city_code == rate.city_code,
                            BullionRateObservation.product_id == rate.product_id,
                            BullionRateObservation.source_product_id == rate.source_product_id,
                            BullionRateObservation.source_published_at == source_pub_utc,
                            BullionRateObservation.validation_status == "VALID",
                        )
                        .order_by(BullionRateObservation.revision_number.desc(), BullionRateObservation.id.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    if winner is None or abs(Decimal(str(winner.price)) - new_price_dec) > Decimal("0.001"):
                        if winner is not None:
                            obs_kwargs["observation_kind"] = "CORRECTION"
                            obs_kwargs["revision_number"] = int(winner.revision_number or 1) + 1
                            obs_kwargs["supersedes_observation_id"] = winner.id
                            obs_kwargs["correction_reason"] = (
                                f"Concurrent correction from {winner.price} to {new_price_dec}"
                            )
                            obs_kwargs["is_changed"] = True
                            with session.begin_nested():
                                session.add(BullionRateObservation(**obs_kwargs))
                                session.flush()
                            inserted_count += 1
                    else:
                        item_logs[-1]["persistence_result"] = "DEDUP_CONCURRENT_SAME_PUBLICATION"

                if should_mirror:
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
                        "price": float(new_price_dec),
                        "currency": rate.currency,
                        "rate_type": rate.rate_type,
                        "published_time": payload.source_updated_time or "",
                        "source": "KJPL",
                    })

        # Update source health status
        for key in {source_key, "KJPL"}:
            ds_record = session.execute(
                select(DataSourceStatus).where(DataSourceStatus.source_name == key)
            ).scalar_one_or_none()
            if ds_record:
                ds_record.last_successful_run = now_utc
                ds_record.current_status = "OPERATIONAL"
                ds_record.error_message = None
                ds_record.updated_at = now_utc

        session.commit()

        if should_mirror and csv_rows_to_append:
            _append_city_csv(target_csv, csv_rows_to_append)

        return {
            "status": "SUCCESS",
            "records_extracted": len(payload.city_rates),
            "records_inserted": inserted_count,
            "records_changed": changed_count,
            "records_quarantined": quarantined_count,
            "item_logs": item_logs,
            "timestamp": now_utc.isoformat(),
        }

    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def _append_city_csv(target_csv: Path, rows: list[dict[str, Any]]) -> None:
    target_csv.parent.mkdir(parents=True, exist_ok=True)
    file_exists = target_csv.exists() and target_csv.stat().st_size > 0
    with target_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "observed_at", "city_code", "city_display_name", "product_id",
            "product_name", "metal", "purity", "weight", "unit", "price",
            "currency", "rate_type", "published_time", "source"
        ])
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _is_clock_only_carryover(session, rate: ParsedCityRate, source_pub_utc: datetime) -> bool:
    """True when the most recent VALID publication for this series has the same IST clock
    time on an earlier date. Used only for CLOCK_ONLY timestamps with an unchanged price."""
    prev = session.execute(
        select(BullionRateObservation)
        .where(
            BullionRateObservation.city_code == rate.city_code,
            BullionRateObservation.product_id == rate.product_id,
            BullionRateObservation.source_product_id == rate.source_product_id,
            BullionRateObservation.validation_status == "VALID",
            BullionRateObservation.source_published_at.is_not(None),
        )
        .order_by(BullionRateObservation.source_published_at.desc(), BullionRateObservation.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if prev is None or prev.source_published_at is None:
        return False
    prev_pub = prev.source_published_at
    if prev_pub.tzinfo is None:
        prev_pub = prev_pub.replace(tzinfo=timezone.utc)
    prev_ist = prev_pub.astimezone(IST)
    new_ist = source_pub_utc.astimezone(IST)
    return (
        prev_ist.date() < new_ist.date()
        and (prev_ist.hour, prev_ist.minute) == (new_ist.hour, new_ist.minute)
    )


def _timestamp_precision(payload: ParsedKJPLPayload) -> str | None:
    """Explicit precision from the parser, else inferred: a source_updated_time string that is
    not a full KJPL date+time means the date was inferred at collection time."""
    if payload.source_timestamp_precision:
        return payload.source_timestamp_precision
    if payload.source_updated_at is None:
        return None
    from app.services.kjpl.parser import parse_full_kjpl_datetime

    text_val = payload.source_updated_time or ""
    if not text_val or parse_full_kjpl_datetime(text_val) is not None:
        return "FULL"
    # Only call it clock-only if the stored instant was actually derived from this HH:MM text.
    import re

    m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", text_val, re.IGNORECASE)
    if not m:
        return "FULL"
    hour, minute = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3).lower() == "pm":
        hour += 12
    local = payload.source_updated_at.astimezone(IST)
    return "CLOCK_ONLY" if (local.hour, local.minute) == (hour, minute) else "FULL"
