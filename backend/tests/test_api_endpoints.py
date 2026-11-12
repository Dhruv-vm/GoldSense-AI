from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.main import app
from app.services.kjpl.city_parser import parse_kjpl_all_city_rates, parse_kjpl_live_feed
from app.services.kjpl.persistence import persist_parsed_payload, seed_bullion_metadata
import app.db.session as db_session
import app.services.data_service as data_service
import app.services.bullion_service as bullion_service
import app.services.alert_service as alert_service


@pytest.fixture(autouse=True)
def isolated_api_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_endpoints.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    TestSession = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_session, "engine", eng)
    monkeypatch.setattr(db_session, "SessionLocal", TestSession)
    monkeypatch.setattr(data_service, "SessionLocal", TestSession)
    monkeypatch.setattr(data_service, "engine", eng)
    monkeypatch.setattr(bullion_service, "SessionLocal", TestSession)
    monkeypatch.setattr(alert_service, "SessionLocal", TestSession)

    fixture_html = (Path(__file__).resolve().parent / "fixtures" / "kjpl" / "kjpl_live_sample.html").read_text(encoding="utf-8")
    live_txt = "\n".join([
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


def test_health_check_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_market_overview_endpoint():
    res = client.get("/api/market/overview")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "kjpl" in data
    assert "market" in data
    assert "derived" in data
    assert data["kjpl"]["gold_mjdta"] > 10000.0
    assert data["market"]["source"].startswith("KJPL")
    assert data["derived"]["global_gold_inr_per_gram"] > 5000.0
    assert "domestic_premium_pct" in data["derived"]


def test_market_refresh_rate_limiting():
    res1 = client.post("/api/market/refresh")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1.get("refreshed") is False
    assert "kjpl-only" in data1.get("message", "").lower() or "single-writer" in data1.get("message", "").lower()


def test_prediction_status_endpoint():
    res = client.get("/api/predictions/latest")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "EXPERIMENTAL_DATA_COLLECTION"
    assert data["is_ready"] is False
    assert data["metrics"]["current_samples"] >= 30
    assert data["metrics"]["current_samples"] < data["metrics"]["required_samples"]
    assert data["metrics"]["required_samples"] == 50


def test_news_endpoints():
    res = client.get("/api/news/latest?limit=5")
    assert res.status_code == 200
    articles = res.json()
    assert len(articles) <= 5
    if len(articles) > 0:
        assert "title" in articles[0]
        assert "sentiment_label" in articles[0]
        assert "is_gold_relevant" in articles[0]

    res_sum = client.get("/api/news/summary")
    assert res_sum.status_code == 200
    assert "positive_ratio" in res_sum.json()


def test_alerts_crud():
    res = client.post("/api/alerts", json={
        "alert_type": "PRICE_ABOVE",
        "target_metric": "KJPL_GOLD",
        "threshold": 14000.0,
        "notes": "Notify when gold crosses ₹14k/g"
    })
    assert res.status_code == 201
    alert_id = res.json()["id"]

    res_list = client.get("/api/alerts")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    res_eval = client.get("/api/alerts/evaluate")
    assert res_eval.status_code == 200
    assert isinstance(res_eval.json(), list)

    res_del = client.delete(f"/api/alerts/{alert_id}")
    assert res_del.status_code == 200


def test_kjpl_history_no_silver_220_fallback_and_blocks_prod_csv(tmp_path: Path, monkeypatch):
    import app.api.routes.kjpl as kjpl_routes

    empty_db = tmp_path / "empty_kjpl.db"
    eng = create_engine(f"sqlite:///{empty_db}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    EmptySession = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    monkeypatch.setattr(db_session, "SessionLocal", EmptySession)

    fake_csv = tmp_path / "kjpl_missing_silver.csv"
    fake_csv.write_text(
        "observed_at,published_time,gold_mjdta,silver_mjdta,source\n"
        "2026-11-10T07:42:32+00:00,Time : 09:40 am,13210.0,,KJPL\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kjpl_routes, "KJPL_CSV", fake_csv)
    monkeypatch.setattr(kjpl_routes, "ENVIRONMENT", "development")

    res_dev = client.get("/api/kjpl/history?limit=10")
    assert res_dev.status_code == 200
    items = res_dev.json()
    assert len(items) == 1
    assert items[0]["gold_mjdta"] == 13210.0
    assert items[0]["silver_mjdta"] is None

    monkeypatch.setattr(kjpl_routes, "ENVIRONMENT", "production")
    res_prod = client.get("/api/kjpl/history?limit=10")
    assert res_prod.status_code == 200
    assert res_prod.json() == []
    eng.dispose()
