from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from app.main import app

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
    assert data["derived"]["global_gold_inr_per_gram"] > 5000.0
    assert "domestic_premium_pct" in data["derived"]


def test_market_refresh_rate_limiting():
    # Calling refresh once
    res1 = client.post("/api/market/refresh")
    assert res1.status_code == 200
    # Immediate follow-up call must be debounced (refreshed=False)
    res2 = client.post("/api/market/refresh")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2.get("refreshed") is False
    assert "cooldown" in data2.get("message", "").lower()


def test_prediction_status_endpoint():
    res = client.get("/api/predictions/latest")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "EXPERIMENTAL_DATA_COLLECTION"
    assert data["is_ready"] is False
    assert data["metrics"]["current_samples"] == 34
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
    # 1. Create alert rule
    res = client.post("/api/alerts", json={
        "alert_type": "PRICE_ABOVE",
        "target_metric": "KJPL_GOLD",
        "threshold": 14000.0,
        "notes": "Notify when gold crosses ₹14k/g"
    }, headers={"X-User-ID": "test_alert_user"})
    assert res.status_code == 201
    alert_id = res.json()["id"]

    # 2. List rules
    res_list = client.get("/api/alerts", headers={"X-User-ID": "test_alert_user"})
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # 3. Evaluate alerts
    res_eval = client.get("/api/alerts/evaluate", headers={"X-User-ID": "test_alert_user"})
    assert res_eval.status_code == 200
    assert isinstance(res_eval.json(), list)

    # 4. Clean up
    res_del = client.delete(f"/api/alerts/{alert_id}", headers={"X-User-ID": "test_alert_user"})
    assert res_del.status_code == 200
