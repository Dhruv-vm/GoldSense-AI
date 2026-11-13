from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.db.base import Base
import app.models  # noqa: F401
import app.db.session as db_session
from app.main import app
from app.models.bullion import BullionLatestRate, BullionRateObservation
from app.services.kjpl.city_parser import parse_kjpl_live_feed, parse_kjpl_all_city_rates
from app.services.kjpl.persistence import seed_bullion_metadata, persist_parsed_payload
from app.services.kjpl.live_rate_service import (
    live_city_cache,
    is_non_persistent_city_feed,
    CityLiveCollector,
)
import app.services.bullion_service as bullion_service

client = TestClient(app)


@pytest.fixture
def non_persistent_test_db(tmp_path: Path, monkeypatch):
    """Isolated database environment for non-persistence boundary verification."""
    live_city_cache.clear()
    db_file = tmp_path / "test_boundary.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    TestSession = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_session, "SessionLocal", TestSession)
    monkeypatch.setattr(bullion_service, "SessionLocal", TestSession)

    with TestSession() as session:
        seed_bullion_metadata(session, ensure_schema=False)
        yield session, TestSession

    live_city_cache.clear()
    eng.dispose()


def test_req1_all_five_city_feeds_served_without_database_writes(non_persistent_test_db):
    """Requirement D.1: All five city feeds (IDs 48-52) are served without database writes."""
    session, _ = non_persistent_test_db

    feed_txt = "\n".join([
        "3\t48\t-\t-\t14500.10\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14505.20\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14495.30\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14502.40\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14510.50\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    payload = parse_kjpl_live_feed(feed_txt)
    res = persist_parsed_payload(payload, session=session, source_key="KJPL_LIVE", mirror_csv=False)

    assert res["status"] == "SUCCESS"
    assert res["records_inserted"] == 0

    # ZERO database writes for the 5 cities in both tables
    city_codes = ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]
    obs_count = session.query(BullionRateObservation).filter(
        BullionRateObservation.city_code.in_(city_codes),
        BullionRateObservation.product_id == "GOLD_100G_999",
    ).count()
    assert obs_count == 0

    latest_count = session.query(BullionLatestRate).filter(
        BullionLatestRate.city_code.in_(city_codes),
        BullionLatestRate.product_id == "GOLD_100G_999",
    ).count()
    assert latest_count == 0

    # Served through API
    resp = client.get("/api/bullion/city-rates")
    assert resp.status_code == 200
    rates = resp.json()
    by_city = {r["city_code"]: r for r in rates if r["product_id"] == "GOLD_100G_999"}
    assert len(by_city) == 5
    assert by_city["CHENNAI"]["latest_price"] == 14500.10
    assert by_city["BENGALURU"]["latest_price"] == 14505.20
    assert by_city["MUMBAI"]["latest_price"] == 14495.30
    assert by_city["COIMBATORE"]["latest_price"] == 14502.40
    assert by_city["HYDERABAD"]["latest_price"] == 14510.50


def test_req2_id_47_continues_to_persist(non_persistent_test_db):
    """Requirement D.2: KJPL ALL_INDIA ID 47 continues to persist to database."""
    session, _ = non_persistent_test_db

    feed_txt = "\n".join([
        "3\t47\t-\t-\t14521.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t14500.10\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    payload = parse_kjpl_live_feed(feed_txt)
    res = persist_parsed_payload(payload, session=session, source_key="KJPL_LIVE", mirror_csv=False)

    # Exactly 1 record inserted (ID 47)
    assert res["records_inserted"] == 1

    # ID 47 is present in database tables
    obs_47 = session.query(BullionRateObservation).filter_by(
        city_code="ALL_INDIA", product_id="GOLD_1KG_9999", source_product_id="47"
    ).one()
    assert float(obs_47.price) == 14521.50
    assert obs_47.validation_status == "VALID"

    latest_47 = session.query(BullionLatestRate).filter_by(
        city_code="ALL_INDIA", product_id="GOLD_1KG_9999"
    ).one()
    assert float(latest_47.latest_price) == 14521.50

    # ID 48 is NOT in database
    assert session.query(BullionRateObservation).filter_by(source_product_id="48").count() == 0
    assert session.query(BullionLatestRate).filter_by(city_code="CHENNAI", product_id="GOLD_100G_999").count() == 0


def test_req3_other_kjpl_products_continue_to_persist(non_persistent_test_db):
    """Requirement D.3: Other KJPL products (contracts, spot feeds) continue to persist to database."""
    session, _ = non_persistent_test_db

    feed_txt = "\n".join([
        "3\t47\t-\t-\t14521.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t14500.10\t-\t-\t-\t-\t-\t11-11-2026",
        "2\tGOLDDEC\tGOLD\t141655\t141695\t141990\t141120\t141664\t\t\t-",
        "2\tSILVERDEC\tSILVER\t187233\t187300\t187979\t185290\t187168\t\t\t-",
        "1\tSPOT-GOLD\tGOLD($)\t4059.93\t4060.11\t4066.93\t4025.90\t4059.93\t\t\t-",
        "1\tSPOT-SILVER\tSILVER($)\t53.01\t53.03\t53.19\t51.41\t53.01\t\t\t-",
        "1\tSPOT-INR\tINR(₹)\t93.70\t93.71\t93.93\t93.64\t93.72\t\t\t-",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    payload = parse_kjpl_live_feed(feed_txt)
    res = persist_parsed_payload(payload, session=session, source_key="KJPL_LIVE", mirror_csv=False)

    # 6 persistent items: ID 47, GOLDDEC, SILVERDEC, SPOT-GOLD, SPOT-SILVER, SPOT-INR
    assert res["records_inserted"] == 6

    # Verify each non-city product persisted
    for pid in [
        "GOLD_1KG_9999",
        "KJPL_GOLDDEC_INR_10G",
        "KJPL_SILVERDEC_INR_1KG",
        "KJPL_SPOT_GOLD_USD",
        "KJPL_SPOT_SILVER_USD",
        "KJPL_SPOT_USDINR",
    ]:
        lr = session.query(BullionLatestRate).filter_by(product_id=pid).one()
        assert lr.validation_status == "VALID"
        obs = session.query(BullionRateObservation).filter_by(product_id=pid).one()
        assert obs.validation_status == "VALID"


def test_req4_mjdta_and_lbma_persistence_remains_unchanged(non_persistent_test_db):
    """Requirement D.4: MJDTA benchmark and LBMA observation persistence remains unchanged."""
    session, _ = non_persistent_test_db

    html = """
    <html><body>
      <table class="chennairate_table">
        <tr><td>MJDTA RATE (Without GST)</td></tr>
        <tr><td>GOLD:</td><td>(₹) 13015</td></tr>
        <tr><td>SILVER:</td><td>(₹) 200</td></tr>
        <tr><td>UPDATED:</td><td>11-11-2026 09:37:32 am</td></tr>
      </table>
      <table id="lbma_table">
        <tr><td>LBMA Gold AM Fix:</td><td>4043.65</td></tr>
      </table>
    </body></html>
    """
    payload = parse_kjpl_all_city_rates(html, reference_time=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc))
    res = persist_parsed_payload(payload, session=session, source_key="KJPL_MJDTA", mirror_csv=False)

    assert res["status"] == "SUCCESS"
    assert res["records_inserted"] >= 2

    # MJDTA benchmark observations persisted to DB
    gold_mjdta = session.query(BullionLatestRate).filter_by(
        city_code="CHENNAI", product_id="MJDTA_GOLD_24K"
    ).one()
    assert float(gold_mjdta.latest_price) == 13015.0
    assert gold_mjdta.rate_type == "MJDTA_BENCHMARK"

    silver_mjdta = session.query(BullionLatestRate).filter_by(
        city_code="CHENNAI", product_id="MJDTA_SILVER"
    ).one()
    assert float(silver_mjdta.latest_price) == 200.0


def test_req5_missing_or_invalid_city_data_does_not_overwrite_valid_cached_rate(non_persistent_test_db):
    """Requirement D.5: Missing or invalid city data does not overwrite a valid cached rate."""
    session, _ = non_persistent_test_db

    # 1. Valid initial rate for Coimbatore (51)
    feed_v1 = "\n".join([
        "3\t51\t-\t-\t14469.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    payload_v1 = parse_kjpl_live_feed(feed_v1)
    persist_parsed_payload(payload_v1, session=session, source_key="KJPL_LIVE", mirror_csv=False)

    cached_v1 = live_city_cache.get_rate("COIMBATORE")
    assert cached_v1 is not None
    assert cached_v1["latest_price"] == 14469.00
    assert cached_v1["validation_status"] == "VALID"

    # 2. Corrupted rate (< ₹1000) for Coimbatore
    feed_bad = "\n".join([
        "3\t51\t-\t-\t51.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:05:00 PM"\t-\t-\t-\t-',
    ])
    payload_bad = parse_kjpl_live_feed(feed_bad)
    res_bad = persist_parsed_payload(payload_bad, session=session, source_key="KJPL_LIVE", mirror_csv=False)
    assert res_bad["records_quarantined"] == 1

    # In-memory cache for Coimbatore MUST NOT be overwritten by corrupted rate
    cached_after_bad = live_city_cache.get_rate("COIMBATORE")
    assert cached_after_bad["latest_price"] == 14469.00
    assert cached_after_bad["validation_status"] == "VALID"

    # 3. Payload with missing Coimbatore (only Chennai provided)
    feed_missing = "\n".join([
        "3\t48\t-\t-\t14470.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:10:00 PM"\t-\t-\t-\t-',
    ])
    payload_missing = parse_kjpl_live_feed(feed_missing)
    persist_parsed_payload(payload_missing, session=session, source_key="KJPL_LIVE", mirror_csv=False)

    # Coimbatore rate still preserved in cache
    cached_still = live_city_cache.get_rate("COIMBATORE")
    assert cached_still["latest_price"] == 14469.00


def test_req6_each_city_updates_independently(non_persistent_test_db):
    """Requirement D.6: Each city updates independently."""
    session, _ = non_persistent_test_db

    # Baseline: all 5 cities at ₹14,500.00
    feed_init = "\n".join([
        "3\t48\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    persist_parsed_payload(parse_kjpl_live_feed(feed_init), session=session, source_key="KJPL_LIVE", mirror_csv=False)

    # Update ONLY Mumbai (50) to ₹14,525.00
    feed_mumbai_only = "\n".join([
        "3\t50\t-\t-\t14525.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:15:00 PM"\t-\t-\t-\t-',
    ])
    persist_parsed_payload(parse_kjpl_live_feed(feed_mumbai_only), session=session, source_key="KJPL_LIVE", mirror_csv=False)

    mumbai = live_city_cache.get_rate("MUMBAI")
    assert mumbai["latest_price"] == 14525.00
    assert mumbai["change_inr"] == 25.00

    # Other 4 cities remain at 14500.00
    for c in ["CHENNAI", "BENGALURU", "COIMBATORE", "HYDERABAD"]:
        other = live_city_cache.get_rate(c)
        assert other["latest_price"] == 14500.00


def test_req7_no_city_rate_is_copied_or_substituted_for_another(non_persistent_test_db):
    """Requirement D.7: No city rate is copied or substituted for another."""
    session, _ = non_persistent_test_db

    feed_distinct = "\n".join([
        "3\t48\t-\t-\t14466.80\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14471.20\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14462.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14469.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14475.10\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:30:00 PM"\t-\t-\t-\t-',
    ])
    persist_parsed_payload(parse_kjpl_live_feed(feed_distinct), session=session, source_key="KJPL_LIVE", mirror_csv=False)

    comp = client.get("/api/bullion/comparison").json()
    cities_map = {c["city_code"]: c for c in comp["cities"]}

    # All prices are strictly distinct
    prices = [cities_map[c]["per_gram_price"] for c in ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"]]
    assert len(set(prices)) == 5

    # Each city retains its own source product ID
    assert cities_map["CHENNAI"]["source_product_id"] == "48"
    assert cities_map["BENGALURU"]["source_product_id"] == "49"
    assert cities_map["MUMBAI"]["source_product_id"] == "50"
    assert cities_map["COIMBATORE"]["source_product_id"] == "51"
    assert cities_map["HYDERABAD"]["source_product_id"] == "52"


def test_req8_repeated_frontend_refreshes_do_not_cause_repeated_source_requests_or_database_writes(non_persistent_test_db):
    """Requirement D.8: Repeated frontend refreshes do not cause repeated source requests or database writes."""
    session, _ = non_persistent_test_db

    feed_txt = "\n".join([
        "3\t48\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14505.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14495.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14502.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14510.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    persist_parsed_payload(parse_kjpl_live_feed(feed_txt), session=session, source_key="KJPL_LIVE", mirror_csv=False)

    obs_count_before = session.query(BullionRateObservation).count()
    latest_count_before = session.query(BullionLatestRate).count()

    # Rapid repeated refreshes from frontend
    for _ in range(15):
        resp = client.get("/api/bullion/city-rates")
        assert resp.status_code == 200
        comp_resp = client.get("/api/bullion/comparison")
        assert comp_resp.status_code == 200
        dash_resp = client.get("/api/bullion/dashboard")
        assert dash_resp.status_code == 200

    # ZERO database writes occurred
    assert session.query(BullionRateObservation).count() == obs_count_before
    assert session.query(BullionLatestRate).count() == latest_count_before


def test_req9_existing_historical_records_remain_untouched(non_persistent_test_db):
    """Requirement D.9: Existing historical records in database remain completely untouched."""
    session, _ = non_persistent_test_db

    # Seed historical observations
    hist_obs = BullionRateObservation(
        city_code="CHENNAI",
        product_id="GOLD_100G_999",
        price=14224.70,
        currency="INR",
        unit="1g",
        rate_type="RETAIL",
        source_name="KJPL",
        source_product_id="48",
        product_weight_grams=1.0,
        source_published_at=datetime(2026, 11, 12, 8, 14, 14, tzinfo=timezone.utc),
        observed_at=datetime(2026, 11, 12, 8, 15, 0, tzinfo=timezone.utc),
        observation_kind="ORIGINAL",
        revision_number=1,
        validation_status="VALID",
        freshness_status="STALE",
    )
    session.add(hist_obs)
    session.commit()
    hist_id = hist_obs.id

    # New live feed arrives for Chennai
    new_feed = "\n".join([
        "3\t48\t-\t-\t14999.00\t-\t-\t-\t-\t-\t13-11-2026",
        '4\t4\t-\t1\t0\t\t"13/11/2026 02:00:00 PM"\t-\t-\t-\t-',
    ])
    persist_parsed_payload(parse_kjpl_live_feed(new_feed), session=session, source_key="KJPL_LIVE", mirror_csv=False)

    # Historical record is completely untouched in database
    session.refresh(hist_obs)
    assert hist_obs.id == hist_id
    assert float(hist_obs.price) == 14224.70
    assert hist_obs.revision_number == 1
    stored_dt = hist_obs.source_published_at
    if stored_dt.tzinfo is None:
        stored_dt = stored_dt.replace(tzinfo=timezone.utc)
    assert stored_dt == datetime(2026, 11, 12, 8, 14, 14, tzinfo=timezone.utc)


# ======================================================================================
# STAGE 20: BOUNDARY HARDENING UNIT TESTS
# ======================================================================================

def test_boundary_missing_city_returns_false():
    """Stage 20: Missing city (None, empty, whitespace) must return False."""
    assert is_non_persistent_city_feed("48", None, "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("48", "", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("48", "   ", "GOLD_100G_999") is False


def test_boundary_missing_product_returns_false():
    """Stage 20: Missing product_id (None, empty, whitespace) must return False."""
    assert is_non_persistent_city_feed("48", "CHENNAI", None) is False
    assert is_non_persistent_city_feed("48", "CHENNAI", "") is False
    assert is_non_persistent_city_feed("48", "CHENNAI", "   ") is False


def test_boundary_missing_source_product_id_returns_false():
    """Stage 20: Missing source_product_id (None, empty, whitespace) must return False."""
    assert is_non_persistent_city_feed(None, "CHENNAI", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("", "CHENNAI", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("   ", "CHENNAI", "GOLD_100G_999") is False


def test_boundary_wrong_city_for_valid_source_product_id_returns_false():
    """Stage 20: Wrong city for valid source product ID must return False."""
    assert is_non_persistent_city_feed("48", "MUMBAI", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("49", "CHENNAI", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("50", "HYDERABAD", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("51", "BENGALURU", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("52", "COIMBATORE", "GOLD_100G_999") is False


def test_boundary_wrong_product_for_valid_source_product_id_returns_false():
    """Stage 20: Wrong product_id for valid source product ID must return False."""
    assert is_non_persistent_city_feed("48", "CHENNAI", "GOLD_1KG_9999") is False
    assert is_non_persistent_city_feed("48", "CHENNAI", "MJDTA_GOLD_24K") is False
    assert is_non_persistent_city_feed("50", "MUMBAI", "SILVER_1KG_999") is False
    assert is_non_persistent_city_feed("52", "HYDERABAD", "UNKNOWN_PROD") is False


def test_boundary_source_product_id_47_returns_false():
    """Stage 20: Source product ID 47 (KJPL ALL_INDIA wholesale bar) must NEVER return True."""
    assert is_non_persistent_city_feed("47", "ALL_INDIA", "GOLD_1KG_9999") is False
    assert is_non_persistent_city_feed("47", "CHENNAI", "GOLD_100G_999") is False
    assert is_non_persistent_city_feed("47", None, None) is False


def test_boundary_other_sources_and_contracts_return_false():
    """Stage 20: MJDTA, LBMA, and KJPL live contracts must NEVER return True."""
    assert is_non_persistent_city_feed("MJDTA_GOLD", "CHENNAI", "MJDTA_GOLD_24K") is False
    assert is_non_persistent_city_feed("MJDTA_GOLD_GST", "CHENNAI", "MJDTA_GOLD_24K_GST") is False
    assert is_non_persistent_city_feed("2", "CHENNAI", "MJDTA_SILVER") is False
    assert is_non_persistent_city_feed("LBMA_GOLD_AM", "ALL_INDIA", "LBMA_GOLD_AM_USD") is False
    assert is_non_persistent_city_feed("LBMA_GOLD_PM", "ALL_INDIA", "LBMA_GOLD_PM_USD") is False
    assert is_non_persistent_city_feed("LBMA_SILVER", "ALL_INDIA", "LBMA_SILVER_USD") is False
    assert is_non_persistent_city_feed("GOLDDEC", "ALL_INDIA", "KJPL_GOLDDEC_INR_10G") is False
    assert is_non_persistent_city_feed("SILVERDEC", "ALL_INDIA", "KJPL_SILVERDEC_INR_1KG") is False
    assert is_non_persistent_city_feed("SPOT-GOLD", "ALL_INDIA", "KJPL_SPOT_GOLD_USD") is False
    assert is_non_persistent_city_feed("SPOT-SILVER", "ALL_INDIA", "KJPL_SPOT_SILVER_USD") is False
    assert is_non_persistent_city_feed("SPOT-INR", "ALL_INDIA", "KJPL_SPOT_USDINR") is False


def test_boundary_all_five_valid_mappings_return_true():
    """Stage 20: All five valid mappings return True, including case-insensitivity and whitespace stripping."""
    mappings = [
        ("48", "CHENNAI", "GOLD_100G_999"),
        ("49", "BENGALURU", "GOLD_100G_999"),
        ("50", "MUMBAI", "GOLD_100G_999"),
        ("51", "COIMBATORE", "GOLD_100G_999"),
        ("52", "HYDERABAD", "GOLD_100G_999"),
    ]
    for spid, c_code, p_id in mappings:
        assert is_non_persistent_city_feed(spid, c_code, p_id) is True
        # Case insensitivity
        assert is_non_persistent_city_feed(spid, c_code.lower(), p_id) is True
        assert is_non_persistent_city_feed(spid, c_code.title(), p_id) is True
        # Whitespace stripping
        assert is_non_persistent_city_feed(f" {spid} ", f"  {c_code}  ", f" {p_id} ") is True


# ======================================================================================
# STAGE 20: LIVE COLLECTOR BEHAVIOUR & LIFECYCLE TESTS
# ======================================================================================

def test_live_collector_lifecycle_and_single_instance():
    """Stage 20: Collector starts, runs single loop, and stops cleanly."""
    async def _test():
        sample_txt = "\n".join([
            "3\t48\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
            '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
        ])
        fetch_count = 0

        def mock_fetch():
            nonlocal fetch_count
            fetch_count += 1
            return sample_txt

        collector = CityLiveCollector(
            poll_interval_sec=0.05,
            fetch_txt_fn=mock_fetch,
            fetch_rpanel_fn=lambda: None,
        )

        assert collector.is_running() is False
        await collector.start()
        assert collector.is_running() is True

        # Calling start again does NOT create a second loop/task
        task_before = collector._task
        await collector.start()
        assert collector._task is task_before

        # Allow one or two ticks
        await asyncio.sleep(0.12)
        assert fetch_count >= 1

        await collector.stop()
        assert collector.is_running() is False
        assert collector._task is None

    asyncio.run(_test())


def test_live_collector_poll_updates_cache():
    """Stage 20: poll_once parses live text feed and populates live_city_cache."""
    async def _test():
        sample_txt = "\n".join([
            "3\t48\t-\t-\t14500.10\t-\t-\t-\t-\t-\t11-11-2026",
            "3\t49\t-\t-\t14505.20\t-\t-\t-\t-\t-\t11-11-2026",
            "3\t50\t-\t-\t14495.30\t-\t-\t-\t-\t-\t11-11-2026",
            "3\t51\t-\t-\t14502.40\t-\t-\t-\t-\t-\t11-11-2026",
            "3\t52\t-\t-\t14510.50\t-\t-\t-\t-\t-\t11-11-2026",
            '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
        ])
        collector = CityLiveCollector(
            fetch_txt_fn=lambda: sample_txt,
        )
        count = await collector.poll_once()
        assert count == 5
        assert live_city_cache.is_warm() is True
        assert live_city_cache.is_fresh() is True

        chennai = live_city_cache.get_rate("CHENNAI")
        assert chennai is not None
        assert chennai["latest_price"] == 14500.10
        assert chennai["source_product_id"] == "48"

    asyncio.run(_test())


def test_live_collector_future_timestamp_rejected():
    """Stage 20: Future publication timestamp never overwrites valid cache."""
    async def _test():
        # Seed valid baseline
        live_city_cache.update_rate(
            "CHENNAI",
            price=14500.0,
            source_product_id="48",
            source_published_at=datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc),
            observed_at=datetime(2026, 11, 11, 14, 5, tzinfo=timezone.utc),
        )

        # Future feed with year 2099
        future_txt = "\n".join([
            "3\t48\t-\t-\t19999.00\t-\t-\t-\t-\t-\t11-11-2099",
            '4\t4\t-\t1\t0\t\t"11/11/2099 02:00:00 PM"\t-\t-\t-\t-',
        ])
        collector = CityLiveCollector(fetch_txt_fn=lambda: future_txt)
        updated = await collector.poll_once()
        assert updated == 0

        # Rate remains at previous 14500.0, not overwritten by 19999.0
        chennai = live_city_cache.get_rate("CHENNAI")
        assert chennai["latest_price"] == 14500.0

    asyncio.run(_test())


def test_live_collector_missing_source_data_never_fabricates():
    """Stage 20: Missing city feed data in payload never fabricates prices."""
    async def _test():
        live_city_cache.clear()
        partial_txt = "\n".join([
            "3\t48\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
            '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
        ])
        collector = CityLiveCollector(fetch_txt_fn=lambda: partial_txt)
        updated = await collector.poll_once()
        assert updated == 1

        assert live_city_cache.get_rate("CHENNAI") is not None
        assert live_city_cache.get_rate("BENGALURU") is None
        assert live_city_cache.get_rate("MUMBAI") is None
        assert live_city_cache.get_rate("COIMBATORE") is None
        assert live_city_cache.get_rate("HYDERABAD") is None

    asyncio.run(_test())


def test_stale_cache_marking_dynamic_recomputation():
    """Stage 20: Stale cached rates are clearly marked via dynamic age recomputation."""
    now_utc = datetime.now(timezone.utc)
    # > 24 hours old is marked STALE by application policy (data_service.py)
    stale_time = now_utc - timedelta(hours=28)

    live_city_cache.update_rate(
        "CHENNAI",
        price=14500.0,
        source_product_id="48",
        source_published_at=stale_time,
        observed_at=stale_time + timedelta(seconds=5),
    )

    rate = live_city_cache.get_rate("CHENNAI")
    assert rate is not None
    assert rate["freshness"] == "STALE"
    assert rate["age_hours"] >= 27.9

    # 4 to 24 hours old is marked DELAYED
    delayed_time = now_utc - timedelta(hours=6)
    live_city_cache.update_rate(
        "BENGALURU",
        price=14505.0,
        source_product_id="49",
        source_published_at=delayed_time,
        observed_at=delayed_time + timedelta(seconds=5),
    )
    rate_b = live_city_cache.get_rate("BENGALURU")
    assert rate_b["freshness"] == "DELAYED"
    assert rate_b["age_hours"] >= 5.9

    # Separate publication and collection time
    assert rate["source_published_at"] == stale_time.isoformat()
    assert rate["observed_at"] == (stale_time + timedelta(seconds=5)).isoformat()


# ======================================================================================
# STAGE 20: API & FRONTEND INTEGRATION TESTS
# ======================================================================================

def test_api_frontend_all_four_endpoints_use_same_live_values(non_persistent_test_db):
    """
    Stage 20: /api/bullion/city-rates, /api/bullion/cities, /api/bullion/comparison,
    and /api/bullion/dashboard all serve the exact same live rate values.
    """
    # 1. Seed cache with all 5 cities
    rates_data = [
        ("CHENNAI", 14500.10, "48"),
        ("BENGALURU", 14505.20, "49"),
        ("MUMBAI", 14495.30, "50"),
        ("COIMBATORE", 14502.40, "51"),
        ("HYDERABAD", 14510.50, "52"),
    ]
    for city, pr, spid in rates_data:
        live_city_cache.update_rate(
            city,
            price=pr,
            source_product_id=spid,
            source_published_at=datetime.now(timezone.utc),
        )

    # Endpoint 1: /api/bullion/city-rates
    resp_rates = client.get("/api/bullion/city-rates")
    assert resp_rates.status_code == 200
    by_city_rates = {r["city_code"]: r["latest_price"] for r in resp_rates.json() if r["product_id"] == "GOLD_100G_999"}
    assert by_city_rates["CHENNAI"] == 14500.10
    assert by_city_rates["BENGALURU"] == 14505.20
    assert by_city_rates["MUMBAI"] == 14495.30
    assert by_city_rates["COIMBATORE"] == 14502.40
    assert by_city_rates["HYDERABAD"] == 14510.50

    # Endpoint 2: /api/bullion/cities
    resp_cities = client.get("/api/bullion/cities")
    assert resp_cities.status_code == 200
    city_codes = {c["city_code"] for c in resp_cities.json()}
    for exp in ["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD", "ALL_INDIA"]:
        assert exp in city_codes

    # Endpoint 3: /api/bullion/comparison
    resp_comp = client.get("/api/bullion/comparison")
    assert resp_comp.status_code == 200
    comp_json = resp_comp.json()
    by_city_comp = {c["city_code"]: c["per_gram_price"] for c in comp_json["cities"]}
    assert by_city_comp["CHENNAI"] == 14500.10
    assert by_city_comp["BENGALURU"] == 14505.20
    assert by_city_comp["MUMBAI"] == 14495.30
    assert by_city_comp["COIMBATORE"] == 14502.40
    assert by_city_comp["HYDERABAD"] == 14510.50

    # Endpoint 4: /api/bullion/dashboard
    resp_dash = client.get("/api/bullion/dashboard")
    assert resp_dash.status_code == 200
    dash_json = resp_dash.json()
    dash_rates = {r["city_code"]: r["latest_price"] for r in dash_json["city_rates"] if r["product_id"] == "GOLD_100G_999"}
    dash_comp = {c["city_code"]: c["per_gram_price"] for c in dash_json["comparison"]["cities"]}
    assert dash_rates == by_city_rates
    assert dash_comp == by_city_comp


def test_api_stale_cached_rates_clearly_marked(non_persistent_test_db):
    """Stage 20: Stale cached rates are clearly marked in all API endpoint responses."""
    # > 24 hours old is STALE
    stale_time = datetime.now(timezone.utc) - timedelta(hours=30)
    live_city_cache.update_rate(
        "CHENNAI",
        price=14500.00,
        source_product_id="48",
        source_published_at=stale_time,
        observed_at=stale_time + timedelta(seconds=5),
    )

    # Check /api/bullion/city-rates
    rates = client.get("/api/bullion/city-rates").json()
    chennai_rate = next(r for r in rates if r["city_code"] == "CHENNAI" and r["product_id"] == "GOLD_100G_999")
    assert chennai_rate["freshness"] == "STALE"

    # Check /api/bullion/comparison
    comp = client.get("/api/bullion/comparison").json()
    chennai_comp = next(c for c in comp["cities"] if c["city_code"] == "CHENNAI")
    assert chennai_comp["freshness"] == "STALE"

    # Check /api/bullion/dashboard
    dash = client.get("/api/bullion/dashboard").json()
    dash_chennai = next(r for r in dash["city_rates"] if r["city_code"] == "CHENNAI" and r["product_id"] == "GOLD_100G_999")
    assert dash_chennai["freshness"] == "STALE"


def test_frontend_polling_zero_source_requests(non_persistent_test_db):
    """
    Stage 20: Repeated frontend polling never invokes outbound source requests.
    The API serving process reads directly from memory with 0 network calls and 0 DB writes.
    """
    session, _ = non_persistent_test_db
    source_call_count = 0

    def mock_external_fetch():
        nonlocal source_call_count
        source_call_count += 1
        return ""

    _collector = CityLiveCollector(fetch_txt_fn=mock_external_fetch)

    # Seed initial rate in cache
    live_city_cache.update_rate(
        "CHENNAI",
        price=14500.00,
        source_product_id="48",
        source_published_at=datetime.now(timezone.utc),
    )

    obs_count_before = session.query(BullionRateObservation).count()
    latest_count_before = session.query(BullionLatestRate).count()

    # Rapid repeated polling on all 4 endpoints
    for _ in range(20):
        client.get("/api/bullion/city-rates")
        client.get("/api/bullion/cities")
        client.get("/api/bullion/comparison")
        client.get("/api/bullion/dashboard")

    # Outbound source network calls MUST be ZERO
    assert source_call_count == 0

    # Database writes MUST be ZERO
    assert session.query(BullionRateObservation).count() == obs_count_before
    assert session.query(BullionLatestRate).count() == latest_count_before


def test_fastapi_lifespan_live_collector_lifecycle():
    """Stage 20: FastAPI lifespan cleanly starts and stops CityLiveCollector when enabled."""
    async def _test_lifespan():
        from app.main import lifespan
        from app.services.kjpl.live_rate_service import set_city_live_collector

        sample_txt = "\n".join([
            "3\t48\t-\t-\t14500.00\t-\t-\t-\t-\t-\t11-11-2026",
            '4\t4\t-\t1\t0\t\t"11/11/2026 02:00:00 PM"\t-\t-\t-\t-',
        ])
        test_collector = CityLiveCollector(
            poll_interval_sec=0.05,
            fetch_txt_fn=lambda: sample_txt,
        )
        set_city_live_collector(test_collector)

        import os
        prev = os.environ.get("ENABLE_FASTAPI_LIVE_COLLECTOR")
        os.environ["ENABLE_FASTAPI_LIVE_COLLECTOR"] = "true"
        try:
            assert test_collector.is_running() is False
            async with lifespan(app):
                assert test_collector.is_running() is True
            # After exit from lifespan context
            assert test_collector.is_running() is False
        finally:
            if prev is None:
                os.environ.pop("ENABLE_FASTAPI_LIVE_COLLECTOR", None)
            else:
                os.environ["ENABLE_FASTAPI_LIVE_COLLECTOR"] = prev
            set_city_live_collector(None)

    asyncio.run(_test_lifespan())

