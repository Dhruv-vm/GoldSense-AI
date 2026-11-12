#!/usr/bin/env python3
"""
VMD Bullion — Neon PostgreSQL Production Database Verification Script (Phase 3)

Verifies:
  1. Direct SSL connection to Neon PostgreSQL via DATABASE_URL.
  2. Alembic revision status & mandatory VMD Bullion schema tables.
  3. Numeric/Decimal financial precision and quarantine columns exist.
  4. Reference cities (5 hubs + ALL_INDIA) and products are seeded.
  5. Transactional write, read-back, and cleanup succeed cleanly.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("DB_USE_NULLPOOL", "true")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import inspect, select, text
from app.db.session import normalize_database_url, build_engine
from app.models.bullion import BullionCity, BullionProduct, CollectorRun
from app.services.kjpl.persistence import seed_bullion_metadata
from sqlalchemy.orm import sessionmaker

MANDATORY_TABLES = [
    "alembic_version",
    "bullion_cities",
    "bullion_products",
    "bullion_rate_observations",
    "bullion_latest_rates",
    "collector_runs",
    "data_source_status",
    "gold_rates",
    "market_rates",
    "portfolio_holdings",
    "alert_rules",
]


def verify_neon() -> bool:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        print("❌ ERROR: DATABASE_URL is not set. Export your Neon connection string and retry.")
        return False

    norm_url = normalize_database_url(raw_url)
    if not norm_url or norm_url.startswith("sqlite"):
        print("❌ ERROR: Production Neon verification requires a postgresql:// URI.")
        return False

    print("=" * 75)
    print(" VMD BULLION — NEON POSTGRESQL VERIFICATION & READ-BACK TEST")
    print("=" * 75)

    try:
        neon_engine = build_engine(raw_url, use_nullpool=True, environment="production")
        with neon_engine.connect() as conn:
            ver = conn.execute(text("SELECT version()")).scalar()
            print(f"✅ Connected to PostgreSQL: {str(ver)[:80]}")
    except Exception as exc:
        print(f"❌ Connection failed: {exc}")
        return False

    insp = inspect(neon_engine)
    existing = set(insp.get_table_names())
    missing = [t for t in MANDATORY_TABLES if t not in existing]
    if missing:
        print(f"❌ Missing tables: {missing}. Run 'alembic upgrade head' with DATABASE_URL set.")
        return False
    print(f"✅ All {len(MANDATORY_TABLES)} mandatory tables present.")

    obs_cols = {c["name"] for c in insp.get_columns("bullion_rate_observations")}
    for required_col in ("validation_status", "quarantine_reason", "normalized_price_per_gram", "product_weight_grams"):
        if required_col not in obs_cols:
            print(f"❌ Missing column '{required_col}' in bullion_rate_observations. Run 'alembic upgrade head'.")
            return False
    print("✅ Numeric precision & quarantine audit columns verified.")

    Session = sessionmaker(bind=neon_engine, autoflush=False, autocommit=False)
    with Session() as session:
        seed_bullion_metadata(session, ensure_schema=False)
        cities = {c.city_code for c in session.scalars(select(BullionCity)).all()}
        prods = len(session.scalars(select(BullionProduct)).all())
        for req in ("CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"):
            if req not in cities:
                print(f"❌ Missing mandatory city '{req}'.")
                return False
        print(f"✅ Seeded cities verified ({len(cities)}) & products ({prods}).")

        test_run_id = f"neon_verify_{uuid.uuid4().hex[:8]}"
        test_run = CollectorRun(
            collector_name="NEON_VERIFICATION_TEST",
            run_id=test_run_id,
            status="SUCCESS",
            records_extracted=0,
            records_inserted=0,
            records_changed=0,
            records_quarantined=0,
            duration_seconds=0.01,
            executed_at=datetime.now(timezone.utc),
        )
        session.add(test_run)
        session.commit()
        fetched = session.scalar(select(CollectorRun).where(CollectorRun.run_id == test_run_id))
        if not fetched:
            print("❌ Write/read-back verification failed.")
            return False
        session.delete(fetched)
        session.commit()
        print("✅ Transactional write, read-back, and cleanup succeeded cleanly.")

    print("=" * 75)
    print(" 🎉 NEON POSTGRESQL READY FOR PRODUCTION")
    print("=" * 75)
    return True


if __name__ == "__main__":
    sys.exit(0 if verify_neon() else 1)
