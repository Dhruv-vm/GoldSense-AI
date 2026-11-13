from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.main import app
from app.services.kjpl.city_parser import parse_kjpl_all_city_rates, parse_kjpl_live_feed
from app.services.kjpl.persistence import persist_parsed_payload, seed_bullion_metadata
import app.db.session as db_session
import app.services.bullion_service as bullion_service
import app.services.data_service as data_service


@pytest.fixture(autouse=True)
def isolated_bullion_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "api_bullion.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    TestSession = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_session, "engine", eng)
    monkeypatch.setattr(db_session, "SessionLocal", TestSession)
    monkeypatch.setattr(bullion_service, "SessionLocal", TestSession)
    monkeypatch.setattr(data_service, "SessionLocal", TestSession)
    monkeypatch.setattr(data_service, "engine", eng)

    fixture_html = (Path(__file__).resolve().parent / "fixtures" / "kjpl" / "kjpl_live_sample.html").read_text(encoding="utf-8")
    live_txt = "\n".join([
        "3\t47\t-\t-\t14521.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14504.50\t-\t-\t-\t-\t-\t11-11-2026",
        "1\tSPOT-GOLD\tGOLD($)\t4059.93\t4060.11\t4066.93\t4025.90\t4059.93\t\t\t-",
        "1\tSPOT-SILVER\tSILVER($)\t53.01\t53.03\t53.19\t51.41\t53.01\t\t\t-",
        "1\tSPOT-INR\tINR(₹)\t93.70\t93.71\t93.93\t93.64\t93.72\t\t\t-",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:06:21 PM"\t-\t-\t-\t-',
    ])
    with TestSession() as session:
        seed_bullion_metadata(session, ensure_schema=False)
        persist_parsed_payload(parse_kjpl_all_city_rates(fixture_html), session=session, mirror_csv=False)
        persist_parsed_payload(parse_kjpl_live_feed(live_txt), session=session, source_key="KJPL_LIVE", mirror_csv=False)

    yield
    eng.dispose()


client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "VMD" in data["service"]
    assert data["database"]["connected"] is True


def test_bullion_cities_endpoint():
    resp = client.get("/api/bullion/cities")
    assert resp.status_code == 200
    cities = resp.json()
    assert len(cities) >= 5
    city_codes = [c["city_code"] for c in cities]
    for c in ("CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"):
        assert c in city_codes
    chennai = next(c for c in cities if c["city_code"] == "CHENNAI")
    assert chennai["is_default"] is True


def test_bullion_latest_summary():
    resp = client.get("/api/bullion/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_city"] == "CHENNAI"
    assert data["data_source"] == "KJPL Exclusive"
    assert len(data["city_tape"]) == 5
    assert data["parity"] is not None
    assert data["parity"]["raw_spot_inr_per_gram"] > 5000.0


def test_bullion_dashboard_consolidated_endpoint():
    resp = client.get("/api/bullion/dashboard?city=CHENNAI&history_limit=10")
    assert resp.status_code == 200
    dash = resp.json()
    for key in ("summary", "cities", "city_rates", "comparison", "monitor", "history"):
        assert key in dash
    assert len(dash["comparison"]["cities"]) == 5


def test_bullion_city_rates_all():
    resp = client.get("/api/bullion/city-rates")
    assert resp.status_code == 200
    rates = resp.json()
    assert isinstance(rates, list)
    assert len(rates) > 0
    first = rates[0]
    for field in ("city_code", "latest_price", "per_gram_price", "source_updated_time", "validation_status"):
        assert field in first


def test_bullion_single_city_and_alias_normalization():
    resp = client.get("/api/bullion/city-rates/bengaluru")
    assert resp.status_code == 200
    rates = resp.json()
    assert len(rates) > 0
    assert all(r["city_code"] == "BENGALURU" for r in rates)

    resp_alias = client.get("/api/bullion/city-rates/bangalore")
    assert resp_alias.status_code == 200
    rates_alias = resp_alias.json()
    assert len(rates_alias) > 0
    assert all(r["city_code"] == "BENGALURU" for r in rates_alias)


def test_bullion_city_comparison_matrix():
    resp = client.get("/api/bullion/comparison")
    assert resp.status_code == 200
    matrix = resp.json()
    assert matrix["benchmark_city"] == "CHENNAI"
    assert len(matrix["cities"]) == 5

    chennai = next(c for c in matrix["cities"] if c["city_code"] == "CHENNAI")
    assert chennai["is_baseline"] is True
    assert chennai["spread_vs_chennai_inr"] == 0.0


def test_bullion_history_endpoint_excludes_quarantined():
    resp = client.get("/api/bullion/history?limit=20")
    assert resp.status_code == 200
    history = resp.json()
    assert isinstance(history, list)
    assert all(h["validation_status"] != "QUARANTINED" for h in history)


def test_data_monitor_status():
    resp = client.get("/api/data-monitor/status")
    assert resp.status_code == 200
    status = resp.json()
    assert "status" in status
    assert "database" in status
    assert "data_quality" in status
    assert "city_freshness" in status
    for c in ("CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"):
        assert c in status["city_freshness"]


def test_data_monitor_collectors_history():
    resp = client.get("/api/data-monitor/collectors")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_health_endpoint_returns_503_when_db_down(monkeypatch):
    import app.main as app_main

    monkeypatch.setattr(
        app_main,
        "check_database_health",
        lambda: {"connected": False, "dialect": "postgresql", "is_postgres": True, "environment": "production", "error": "connection refused"},
    )
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["database"]["connected"] is False


def test_neon_database_url_normalization_and_production_fail_closed():
    url = db_session.normalize_database_url("postgres://user:pass@ep-cool-host.us-east-2.aws.neon.tech/neondb")
    assert url is not None
    assert url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in url

    local_url = db_session.normalize_database_url("postgresql://user:pass@localhost:5432/vmd")
    assert local_url == "postgresql+psycopg://user:pass@localhost:5432/vmd"

    with pytest.raises(RuntimeError, match="production"):
        db_session.build_engine(url="", environment="production")

    with pytest.raises(RuntimeError, match="production"):
        db_session.build_engine(url="sqlite:///tmp/forbidden.db", environment="production")


def test_bullion_sse_stream_generator_emits_snapshot(monkeypatch):
    import asyncio
    import json
    import app.api.routes.bullion as bullion_routes

    class _FakeRequest:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1

    async def _fast_sleep(_seconds: float):
        return None

    monkeypatch.setattr(bullion_routes.asyncio, "sleep", _fast_sleep)

    async def _collect_first_event():
        gen = bullion_routes._bullion_sse_generator(_FakeRequest())
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
        return chunks

    events = asyncio.run(_collect_first_event())
    assert len(events) >= 1
    assert events[0].startswith("event: snapshot\ndata: ")
    payload = json.loads(events[0].split("data: ", 1)[1].strip())
    assert "summary" in payload
    assert "monitor" in payload


def test_five_independent_cities_api_and_timestamp_ist_conversion(monkeypatch):
    """Verify distinct 5-city rates (no substitution), metadata fields, and UTC->IST formatting."""
    # Update isolated DB with distinct prices per city & explicit IST source timestamp
    live_distinct = "\n".join([
        "3\t47\t-\t-\t14483.80\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t48\t-\t-\t14466.80\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t49\t-\t-\t14471.20\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t50\t-\t-\t14462.50\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t51\t-\t-\t14469.00\t-\t-\t-\t-\t-\t11-11-2026",
        "3\t52\t-\t-\t14475.10\t-\t-\t-\t-\t-\t11-11-2026",
        '4\t4\t-\t1\t0\t\t"11/11/2026 02:30:00 PM"\t-\t-\t-\t-',
    ])
    with db_session.SessionLocal() as s:
        persist_parsed_payload(parse_kjpl_live_feed(live_distinct), session=s, source_key="KJPL_LIVE", mirror_csv=False)

    comp = client.get("/api/bullion/comparison").json()
    by_city = {c["city_code"]: c for c in comp["cities"]}
    assert by_city["CHENNAI"]["per_gram_price"] == 14466.80
    assert by_city["BENGALURU"]["per_gram_price"] == 14471.20
    assert by_city["MUMBAI"]["per_gram_price"] == 14462.50
    assert by_city["COIMBATORE"]["per_gram_price"] == 14469.00
    assert by_city["HYDERABAD"]["per_gram_price"] == 14475.10

    assert by_city["BENGALURU"]["source_product_id"] == "49"
    assert by_city["COIMBATORE"]["unit"] == "1g"
    assert by_city["HYDERABAD"]["validation_status"] == "VALID"
    assert "02:30 PM IST" in by_city["CHENNAI"]["source_updated_time"]


def test_production_mode_blocks_stale_csv_fallback_and_handles_market_closed(tmp_path: Path, monkeypatch):
    """In production with empty DB, API must never silently return local CSV rows; market closed retains valid rate."""
    from app.services.kjpl.live_rate_service import live_city_cache
    live_city_cache.clear()
    empty_db = tmp_path / "empty_prod.db"
    eng = create_engine(f"sqlite:///{empty_db}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    EmptySession = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    with EmptySession() as s:
        seed_bullion_metadata(s, ensure_schema=False)

    monkeypatch.setattr(db_session, "SessionLocal", EmptySession)
    monkeypatch.setattr(bullion_service, "SessionLocal", EmptySession)
    monkeypatch.setattr(bullion_service, "ENVIRONMENT", "production")

    rates_resp = client.get("/api/bullion/city-rates")
    assert rates_resp.status_code == 200
    assert rates_resp.json() == []

    comp_resp = client.get("/api/bullion/comparison").json()
    assert all(c["freshness"] == "SOURCE_UNAVAILABLE" and c["per_gram_price"] is None for c in comp_resp["cities"])
    eng.dispose()
