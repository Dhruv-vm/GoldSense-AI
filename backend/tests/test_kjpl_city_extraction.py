from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.services.kjpl.city_parser import parse_kjpl_all_city_rates
from app.services.kjpl.persistence import (
    seed_bullion_metadata,
    persist_parsed_payload,
    DEFAULT_CITIES,
)
from app.db.session import SessionLocal
from app.models.bullion import (
    BullionCity,
    BullionProduct,
    BullionRateObservation,
    BullionLatestRate,
    DataSourceStatus,
)

SAMPLE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kjpl" / "kjpl_live_sample.html"


def test_city_parser_extracts_all_five_cities():
    html = SAMPLE_FIXTURE.read_text(encoding="utf-8")
    payload = parse_kjpl_all_city_rates(html)

    assert payload.mjdta_gold == 13040.0
    assert payload.mjdta_silver == 210.0
    assert payload.mjdta_gold_with_gst == 13431.20
    assert payload.source_updated_time == "Time : 09:35 am"

    # Verify all 5 mandatory cities exist
    city_codes = {r.city_code for r in payload.city_rates}
    mandatory = {"CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"}
    for m in mandatory:
        assert m in city_codes, f"Mandatory city {m} missing from parsed rates"

    # Verify Bengaluru is strictly displayed as Bengaluru (even if source says Bangalore)
    bangalore_rate = next(r for r in payload.city_rates if r.city_code == "BENGALURU")
    assert bangalore_rate.city_display_name == "Bengaluru"
    assert bangalore_rate.price == 1309200.0  # 100g rate

    # Verify Chennai rate
    chennai_100g = next(r for r in payload.city_rates if r.city_code == "CHENNAI" and r.product_id == "GOLD_100G_999")
    assert chennai_100g.price == 1308500.0

    # Verify Mumbai rate
    mumbai_rate = next(r for r in payload.city_rates if r.city_code == "MUMBAI")
    assert mumbai_rate.price == 1307800.0

    # Verify Coimbatore rate
    coimbatore_rate = next(r for r in payload.city_rates if r.city_code == "COIMBATORE")
    assert coimbatore_rate.price == 1308900.0

    # Verify Hyderabad rate
    hyderabad_rate = next(r for r in payload.city_rates if r.city_code == "HYDERABAD")
    assert hyderabad_rate.price == 1309500.0

    # Verify National Wholesale 1KG
    kg_rate = next(r for r in payload.city_rates if r.product_id == "GOLD_1KG_9999")
    assert kg_rate.price == 13085000.0
    assert kg_rate.purity == 0.9999


def test_seed_bullion_metadata_is_idempotent():
    with SessionLocal() as session:
        seed_bullion_metadata(session)
        cities = session.query(BullionCity).all()
        assert len(cities) >= 6
        codes = {c.city_code for c in cities}
        assert "CHENNAI" in codes
        assert "BENGALURU" in codes
        assert "MUMBAI" in codes
        assert "COIMBATORE" in codes
        assert "HYDERABAD" in codes

        # Run second time - should not fail or duplicate
        seed_bullion_metadata(session)
        assert session.query(BullionCity).filter_by(city_code="CHENNAI").count() == 1


def test_persistence_unchanged_price_detection():
    html = SAMPLE_FIXTURE.read_text(encoding="utf-8")
    payload = parse_kjpl_all_city_rates(html)

    with SessionLocal() as session:
        # Clear existing rates
        session.query(BullionLatestRate).delete()
        session.query(BullionRateObservation).delete()
        session.commit()

        # Run 1: First insert
        res1 = persist_parsed_payload(payload, session=session)
        assert res1["status"] == "SUCCESS"
        assert res1["records_inserted"] > 0
        assert res1["records_changed"] > 0
        initial_obs_count = session.query(BullionRateObservation).count()
        assert initial_obs_count == res1["records_inserted"]

        # Run 2: Exact same payload (rates unchanged)
        res2 = persist_parsed_payload(payload, session=session)
        assert res2["status"] == "SUCCESS"
        assert res2["records_inserted"] == 0
        assert res2["records_changed"] == 0
        # No artificial observation duplicates created
        assert session.query(BullionRateObservation).count() == initial_obs_count
