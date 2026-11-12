from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.services.kjpl.city_parser import parse_kjpl_all_city_rates, parse_kjpl_live_feed
from app.services.kjpl.persistence import seed_bullion_metadata, persist_parsed_payload
from app.services.kjpl.validator import validate_bullion_observation
from app.models.bullion import BullionCity, BullionRateObservation, BullionLatestRate

SAMPLE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kjpl" / "kjpl_live_sample.html"


@pytest.fixture
def isolated_session(tmp_path: Path):
    db_file = tmp_path / "test_bullion.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    TestSession = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    with TestSession() as session:
        seed_bullion_metadata(session, ensure_schema=False)
        yield session
    eng.dispose()


def test_city_parser_extracts_all_five_cities():
    html = SAMPLE_FIXTURE.read_text(encoding="utf-8")
    payload = parse_kjpl_all_city_rates(html)

    assert payload.mjdta_gold == 13040.0
    assert payload.mjdta_silver == 210.0
    assert payload.mjdta_gold_with_gst == 13431.20
    assert payload.source_updated_time == "Time : 09:35 am"

    city_codes = {r.city_code for r in payload.city_rates}
    for m in ("CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"):
        assert m in city_codes, f"Mandatory city {m} missing from parsed rates"

    bangalore_rate = next(r for r in payload.city_rates if r.city_code == "BENGALURU")
    assert bangalore_rate.city_display_name == "Bengaluru"
    assert bangalore_rate.price == 1309200.0
    assert bangalore_rate.normalized_price_per_gram == 13092.0

    kg_rate = next(r for r in payload.city_rates if r.product_id == "GOLD_1KG_9999")
    assert kg_rate.price == 13085000.0
    assert kg_rate.product_weight_grams == 1000.0
    assert kg_rate.normalized_price_per_gram == 13085.0
    assert kg_rate.purity == 0.9999


def test_live_feed_parser_handles_kjpl_txt_and_ws_units():
    sample_txt = "\n".join([
        "3\t47\t-\t-\t14521.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "2\tGOLDDEC\tGOLD\t141655\t141695\t141990\t141120\t141664\t\t\t-",
        "2\tSILVERDEC\tSILVER\t187233\t187300\t187979\t185290\t187168\t\t\t-",
        "1\tSPOT-GOLD\tGOLD($)\t4059.93\t4060.11\t4066.93\t4025.90\t4059.93\t\t\t-",
        "1\tSPOT-SILVER\tSILVER($)\t53.01\t53.03\t53.19\t51.41\t53.01\t\t\t-",
        "1\tSPOT-INR\tINR(₹)\t93.70\t93.71\t93.93\t93.64\t93.72\t\t\t-",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:06:21 PM"\t-\t-\t-\t-',
    ])
    payload = parse_kjpl_live_feed(sample_txt)
    assert payload.market_status == "OPEN"
    assert payload.rate_display_enabled is True
    assert payload.source_updated_at is not None
    assert payload.source_updated_at.year == 2026
    assert len(payload.city_rates) == 11

    chennai = next(r for r in payload.city_rates if r.city_code == "CHENNAI" and r.product_id == "GOLD_100G_999")
    assert chennai.price == 14504.50
    assert chennai.product_weight_grams == 1.0
    assert chennai.normalized_price_per_gram == 14504.50

    golddec = next(r for r in payload.city_rates if r.product_id == "KJPL_GOLDDEC_INR_10G")
    assert golddec.normalized_price_per_gram == 14169.50
    assert golddec.buy_price == 141655.0

    spot_gold = next(r for r in payload.city_rates if r.product_id == "KJPL_SPOT_GOLD_USD")
    assert spot_gold.currency == "USD"
    assert spot_gold.unit == "oz"
    assert spot_gold.price == 4060.11


def test_regression_corruption_quarantine_rules():
    # 1. Silver ₹200 / ₹210 passed off as MJDTA Gold INR/g
    r1 = validate_bullion_observation(product_id="MJDTA_GOLD_24K", metal="GOLD", currency="INR", unit="1g", weight_value=1.0, price=200.0)
    assert r1.validation_status == "QUARANTINED"

    # 2. LBMA Gold USD 4043.65 passed off as MJDTA Gold INR/g
    r2 = validate_bullion_observation(product_id="MJDTA_GOLD_24K", metal="GOLD", currency="INR", unit="1g", weight_value=1.0, price=4043.65)
    assert r2.validation_status == "QUARANTINED"

    # 3. LBMA Silver USD 51.99 passed off as MJDTA Silver INR/g (must reject < ₹80/g)
    r3 = validate_bullion_observation(product_id="MJDTA_SILVER", metal="SILVER", currency="INR", unit="1g", weight_value=1.0, price=51.99)
    assert r3.validation_status == "QUARANTINED"

    # 4. City weight ₹100 or com_id ₹51/52 parsed as 100g gold price
    r4 = validate_bullion_observation(product_id="GOLD_100G_999", metal="GOLD", currency="INR", unit="100g", weight_value=100.0, price=100.0)
    assert r4.validation_status == "QUARANTINED"
    r5 = validate_bullion_observation(product_id="GOLD_100G_999", metal="GOLD", currency="INR", unit="100g", weight_value=100.0, price=51.0, source_product_id="51")
    assert r5.validation_status == "QUARANTINED"

    # 5. Live HTML combined table + LBMA table must NOT contaminate MJDTA INR
    contaminated_html = """
    <html><body>
      <span class="mjdma_data">Time : 09:37 am</span>
      <span class="gold-rate">13015</span>
      <span class="silver-rate">200</span>
      <table class="mjdmahead"><tr><td>GOLD 13015</td><td>SILVER 200</td></tr></table>
      <table class="chennairate_table">
        <tr><td>TODAY'S RATE - LBMA LONDON</td></tr>
        <tr><td>GOLD AM Fix:</td><td>($) 4073.70</td></tr>
        <tr><td>SILVER Fix:</td><td>($) 52.2850</td></tr>
      </table>
      <table class="chennairate_table">
        <tr><td>MJDTA RATE (Without GST)</td></tr>
        <tr><td>GOLD:</td><td>(₹) 13015</td></tr>
        <tr><td>SILVER:</td><td>(₹) 200</td></tr>
        <tr><td>UPDATED:</td><td>11-11-2026 09:37:32 am</td></tr>
      </table>
    </body></html>
    """
    parsed = parse_kjpl_all_city_rates(contaminated_html)
    mjdta_gold = [r for r in parsed.city_rates if r.product_id == "MJDTA_GOLD_24K"]
    assert len(mjdta_gold) == 1
    assert mjdta_gold[0].price == 13015.0
    lbma_silver = [r for r in parsed.city_rates if r.product_id == "LBMA_SILVER_USD"]
    assert len(lbma_silver) == 1 and lbma_silver[0].currency == "USD"
    assert parsed.source_updated_at.day == 11 and parsed.source_updated_at.month == 11


def test_seed_bullion_metadata_is_idempotent(isolated_session):
    cities = isolated_session.query(BullionCity).all()
    assert len(cities) >= 6
    codes = {c.city_code for c in cities}
    for c in ("CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"):
        assert c in codes

    seed_bullion_metadata(isolated_session)
    assert isolated_session.query(BullionCity).filter_by(city_code="CHENNAI").count() == 1


def test_persistence_unchanged_price_detection_and_quarantine(isolated_session, tmp_path: Path):
    html = SAMPLE_FIXTURE.read_text(encoding="utf-8")
    payload = parse_kjpl_all_city_rates(html)
    tmp_csv = tmp_path / "city_rates.csv"

    res1 = persist_parsed_payload(payload, session=isolated_session, mirror_csv=True, csv_path=tmp_csv)
    assert res1["status"] == "SUCCESS"
    assert res1["records_inserted"] > 0
    assert res1["records_changed"] > 0
    initial_obs_count = isolated_session.query(BullionRateObservation).count()
    assert initial_obs_count == res1["records_inserted"]

    # Run 2: Exact same payload -> zero duplicate observation inserts
    res2 = persist_parsed_payload(payload, session=isolated_session, mirror_csv=True, csv_path=tmp_csv)
    assert res2["status"] == "SUCCESS"
    assert res2["records_inserted"] == 0
    assert res2["records_changed"] == 0
    assert isolated_session.query(BullionRateObservation).count() == initial_obs_count


def test_five_city_ids_47_to_52_independent_normalization_and_ws(isolated_session):
    """Verify all 5 cities (48..52) + 47 parse independently with 1g unit, Decimal precision, and no division by 100."""
    ws_frame = "\n".join([
        "3|47|-|14483.80",
        "3|48|-|14466.80",
        "3|49|-|14471.20",
        "3|50|-|14462.50",
        "3|51|-|14469.00",
        "3|52|-|14475.10",
        "4|4|1|0|",
    ])
    rpanel_mock = {
        "commoditydetails": [
            {"com_id": "47", "com_name": "GOLD 1KG 99.99", "com_weight": "1.000"},
            {"com_id": "48", "com_name": "GOLD 100 GMS 999 Chennai", "com_weight": "1.000"},
            {"com_id": "49", "com_name": "Gold 100 GMS 999 Bangalore", "com_weight": "1.000"},
            {"com_id": "50", "com_name": "Gold 100 GMS 999 Mumbai", "com_weight": "1.000"},
            {"com_id": "51", "com_name": "Gold 100 GMS 999 Coimbatore", "com_weight": "1.000"},
            {"com_id": "52", "com_name": "GOLD 100 GMS 999 Hyderabad", "com_weight": "1.000"},
        ],
        "rpaneldata": {"lastupdatetime": "11/11/2026 02:45:00 PM"},
    }
    payload = parse_kjpl_live_feed(ws_frame, rpanel_json=rpanel_mock, source_label="KJPL_LIVE_WS")
    assert len(payload.city_rates) == 6
    assert len(payload.quarantined_rates) == 0

    expected = {
        "ALL_INDIA": ("47", "GOLD_1KG_9999", 0.9999, 14483.80),
        "CHENNAI": ("48", "GOLD_100G_999", 0.999, 14466.80),
        "BENGALURU": ("49", "GOLD_100G_999", 0.999, 14471.20),
        "MUMBAI": ("50", "GOLD_100G_999", 0.999, 14462.50),
        "COIMBATORE": ("51", "GOLD_100G_999", 0.999, 14469.00),
        "HYDERABAD": ("52", "GOLD_100G_999", 0.999, 14475.10),
    }
    persist_parsed_payload(payload, session=isolated_session, source_key="KJPL_LIVE", mirror_csv=False)

    for city, (src_id, pid, purity, price) in expected.items():
        latest = isolated_session.query(BullionLatestRate).filter_by(city_code=city, product_id=pid).one()
        assert float(latest.latest_price) == pytest.approx(price, abs=0.01)
        assert float(latest.normalized_price_per_gram) == pytest.approx(price, abs=0.01)
        assert float(latest.product_weight_grams) == pytest.approx(1.0)
        assert latest.unit == "1g"
        assert latest.source_product_id == src_id
        assert latest.validation_status == "VALID"
        assert float(latest.normalized_price_per_gram) > 1000.0


def test_sub_1000_city_gold_rejected_across_all_five_ids(isolated_session):
    """Any value < ₹1,000 (e.g. ₹100 weight, ₹51/52 com_id, or ₹144.67 /100 misdivision) is quarantined for all 5 cities."""
    corrupt_txt = "\n".join([
        "3\t47\t-\t-\t144.84\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t100.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t100.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t144.63\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t51.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t52.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:45:00 PM"\t-\t-\t-\t-',
    ])
    payload = parse_kjpl_live_feed(corrupt_txt)
    assert len(payload.city_rates) == 0
    assert len(payload.quarantined_rates) == 6
    res = persist_parsed_payload(payload, session=isolated_session, source_key="KJPL_LIVE", mirror_csv=False)
    assert res["records_quarantined"] == 6
    assert isolated_session.query(BullionLatestRate).count() == 0
    assert isolated_session.query(BullionRateObservation).filter_by(validation_status="QUARANTINED").count() == 6


def test_legacy_db_metadata_repair_and_collector_execution(isolated_session, tmp_path: Path, monkeypatch, capsys):
    """Verify seed_bullion_metadata repairs legacy weight=100 metadata and collect_kjpl_csv persists all 5 cities."""
    from app.models.bullion import BullionProduct
    import app.db.session as db_session
    import scripts.collect_kjpl_csv as collector

    # Simulate legacy prototype metadata (weight=100, unit='100g')
    prod = isolated_session.query(BullionProduct).filter_by(product_id="GOLD_100G_999").one()
    prod.weight = 100.0
    prod.unit = "100g"
    isolated_session.commit()

    seed_bullion_metadata(isolated_session, ensure_schema=False)
    isolated_session.refresh(prod)
    assert float(prod.weight) == pytest.approx(1.0)
    assert prod.unit == "1g"

    # Point SessionLocal to isolated DB and execute collect_kjpl_csv.run_collection
    TestSession = sessionmaker(bind=isolated_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(db_session, "SessionLocal", TestSession)
    monkeypatch.setenv("ENABLE_CSV_MIRROR", "false")

    html_mjdta = """
    <html><body>
      <table class="chennairate_table">
        <tr><td>MJDTA RATE (Without GST)</td></tr>
        <tr><td>GOLD:</td><td>(₹) 13015</td></tr>
        <tr><td>SILVER:</td><td>(₹) 200</td></tr>
        <tr><td>UPDATED:</td><td>11-11-2026 09:37:32 am</td></tr>
      </table>
    </body></html>
    """
    txt_live = "\n".join([
        "3\t47\t-\t-\t14487.70\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t14470.70\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14475.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14468.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14472.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14479.00\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:45:00 PM"\t-\t-\t-\t-',
    ])
    out = collector.run_collection(html_override=html_mjdta, txt_override=txt_live)
    assert out["status"] == "SUCCESS"
    assert out["persistence"]["records_extracted"] == 8  # MJDTA Gold, Silver + 6 live Type 3 products

    captured = capsys.readouterr().out
    assert "[COLLECTOR_ITEM]" in captured
    assert '"city": "COIMBATORE"' in captured
    assert '"normalized_unit": "INR/g"' in captured

    for c in ("CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"):
        row = isolated_session.query(BullionLatestRate).filter_by(city_code=c, product_id="GOLD_100G_999").one()
        assert float(row.normalized_price_per_gram) > 14000.0


def test_stage18_source_specific_kjpl_datetime_parsing():
    """Stage 18: Type-4 slash timestamps are strictly MM/DD/YYYY; MJDTA dash timestamps are strictly DD-MM-YYYY."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from app.services.kjpl.parser import parse_full_kjpl_datetime, parse_kjpl_type4_datetime

    ist = ZoneInfo("Asia/Kolkata")

    dt1 = parse_kjpl_type4_datetime("11/12/2026 01:44:14 PM")
    assert dt1 == datetime(2026, 11, 12, 13, 44, 14, tzinfo=ist)
    assert dt1.astimezone(timezone.utc) == datetime(2026, 11, 12, 8, 14, 14, tzinfo=timezone.utc)

    dt2 = parse_kjpl_type4_datetime("11/12/2026 02:18:44 PM")
    assert dt2 == datetime(2026, 11, 12, 14, 18, 44, tzinfo=ist)
    assert dt2.astimezone(timezone.utc) == datetime(2026, 11, 12, 8, 48, 44, tzinfo=timezone.utc)

    # Single-digit components
    dt_single = parse_kjpl_type4_datetime("1/5/2026 09:05:00 AM")
    assert dt_single == datetime(2026, 1, 5, 9, 5, 0, tzinfo=ist)
    dt_dash_single = parse_full_kjpl_datetime("5-1-2026 09:05 am")
    assert dt_dash_single == datetime(2026, 1, 5, 9, 5, 0, tzinfo=ist)

    # MJDTA dash-separated dates
    dt_mjdta = parse_full_kjpl_datetime("12-11-2026 09:38:00 am")
    assert dt_mjdta == datetime(2026, 11, 12, 9, 38, 0, tzinfo=ist)

    # Invalid dates & cross-contract rejection
    assert parse_kjpl_type4_datetime("13/12/2026 01:44:14 PM") is None  # month 13 invalid
    assert parse_full_kjpl_datetime("32-11-2026 09:30 am") is None
    assert parse_full_kjpl_datetime("11/12/2026 01:44:14 PM") is None  # ambiguous slash rejected without Type-4 contract


def test_stage18_universal_future_and_invalid_timestamp_quarantine(isolated_session):
    """Stage 18: Future or invalid source timestamps are quarantined across KJPL_LIVE, RETAIL, WHOLESALE, MJDTA_BENCHMARK."""
    from datetime import datetime, timezone
    from app.models.bullion import BullionLatestRate, BullionRateObservation
    from app.services.kjpl.persistence import persist_parsed_payload, seed_bullion_metadata

    seed_bullion_metadata(isolated_session, ensure_schema=False)

    # 1. Future Type-4 timestamp (12/11/2026 when observed_at is 2026-11-12) must be QUARANTINED for 47..52 & KJPL_LIVE
    future_txt = "\n".join([
        "3\t47\t-\t-\t14183.30\t-\t-\t-\t-\t-\t12-11-2026",
        "3\t48\t-\t-\t14166.30\t-\t-\t-\t-\t-\t12-11-2026",
        "3\t49\t-\t-\t14166.30\t-\t-\t-\t-\t-\t12-11-2026",
        "3\t50\t-\t-\t14166.30\t-\t-\t-\t-\t-\t12-11-2026",
        "3\t51\t-\t-\t14166.30\t-\t-\t-\t-\t-\t12-11-2026",
        "3\t52\t-\t-\t14166.30\t-\t-\t-\t-\t-\t12-11-2026",
        "2\tGOLDDEC\tGOLD\t137913\t137881\t138500\t137500\t137900\t\t\t-",
        '4\t4\t-\t1\t0\t\t"12/11/2026 02:18:44 PM"\t-\t-\t-\t-',
    ])
    payload_future = parse_kjpl_live_feed(future_txt)
    payload_future.observed_at = datetime(2026, 11, 12, 8, 48, 51, tzinfo=timezone.utc)
    res = persist_parsed_payload(payload_future, session=isolated_session, source_key="KJPL_LIVE", mirror_csv=False)
    assert res["records_quarantined"] == 7
    assert res["records_inserted"] == 0
    assert isolated_session.query(BullionLatestRate).count() == 0

    # 2. Invalid/unparseable Type-4 timestamp must never fall back to observed_at
    bad_ts_txt = "\n".join([
        "3\t48\t-\t-\t14166.30\t-\t-\t-\t-\t-\t12-11-2026",
        '4\t4\t-\t1\t0\t\t"13/12/2026 02:18:44 PM"\t-\t-\t-\t-',
    ])
    payload_bad = parse_kjpl_live_feed(bad_ts_txt)
    payload_bad.observed_at = datetime(2026, 11, 12, 8, 50, 0, tzinfo=timezone.utc)
    assert payload_bad.source_updated_at is None
    res_bad = persist_parsed_payload(payload_bad, session=isolated_session, source_key="KJPL_LIVE", mirror_csv=False)
    assert res_bad["records_quarantined"] == 1
    bad_obs = isolated_session.query(BullionRateObservation).order_by(BullionRateObservation.id.desc()).first()
    assert bad_obs.validation_status == "QUARANTINED"
    assert bad_obs.source_published_at is None

    # 3. Valid MJDTA unchanged-price distinct publications & ALL_INDIA isolation
    from app.services.kjpl.city_parser import parse_kjpl_all_city_rates
    from app.services.prediction.mjdta_series import load_mjdta_observations_from_db

    for day in ("11-11-2026", "12-11-2026"):
        html = f"""
        <html><body>
          <table class="chennairate_table">
            <tr><td>MJDTA RATE (Without GST)</td></tr>
            <tr><td>GOLD:</td><td>(₹) 12815</td></tr>
            <tr><td>SILVER:</td><td>(₹) 200</td></tr>
            <tr><td>UPDATED:</td><td>{day} 09:38:00 am</td></tr>
          </table>
        </body></html>
        """
        p = parse_kjpl_all_city_rates(html, reference_time=datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc))
        persist_parsed_payload(p, session=isolated_session, source_key="KJPL_MJDTA", mirror_csv=False)

    obs_list, _ = load_mjdta_observations_from_db(isolated_session)
    assert len(obs_list) == 2
    assert all(pt.gold_mjdta_inr_per_g == 12815.0 for pt in obs_list)
