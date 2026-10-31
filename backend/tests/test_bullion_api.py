from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "VMD" in data["service"]


def test_bullion_cities_endpoint():
    resp = client.get("/api/bullion/cities")
    assert resp.status_code == 200
    cities = resp.json()
    assert len(cities) >= 5
    city_codes = [c["city_code"] for c in cities]
    assert "CHENNAI" in city_codes
    assert "BENGALURU" in city_codes
    assert "MUMBAI" in city_codes
    assert "COIMBATORE" in city_codes
    assert "HYDERABAD" in city_codes

    # Check default city is Chennai
    chennai = next(c for c in cities if c["city_code"] == "CHENNAI")
    assert chennai["is_default"] is True


def test_bullion_latest_summary():
    resp = client.get("/api/bullion/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_city"] == "CHENNAI"
    assert "city_tape" in data
    assert len(data["city_tape"]) >= 5


def test_bullion_city_rates_all():
    resp = client.get("/api/bullion/city-rates")
    assert resp.status_code == 200
    rates = resp.json()
    assert isinstance(rates, list)
    assert len(rates) > 0
    first = rates[0]
    assert "city_code" in first
    assert "latest_price" in first
    assert "per_gram_price" in first
    assert "source_updated_time" in first


def test_bullion_single_city_and_alias_normalization():
    # Test Bengaluru
    resp = client.get("/api/bullion/city-rates/bengaluru")
    assert resp.status_code == 200
    rates = resp.json()
    assert len(rates) > 0
    assert all(r["city_code"] == "BENGALURU" for r in rates)

    # Test Bangalore normalization -> returns BENGALURU
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
    assert "cities" in matrix
    assert len(matrix["cities"]) == 5

    # Confirm Chennai has 0 spread against itself
    chennai = next(c for c in matrix["cities"] if c["city_code"] == "CHENNAI")
    assert chennai["is_baseline"] is True
    assert chennai["spread_vs_chennai_inr"] == 0.0


def test_bullion_history_endpoint():
    resp = client.get("/api/bullion/history?limit=10")
    assert resp.status_code == 200
    history = resp.json()
    assert isinstance(history, list)


def test_data_monitor_status():
    resp = client.get("/api/data-monitor/status")
    assert resp.status_code == 200
    status = resp.json()
    assert "status" in status
    assert "database" in status
    assert "city_freshness" in status
    assert "CHENNAI" in status["city_freshness"]
    assert "BENGALURU" in status["city_freshness"]
    assert "MUMBAI" in status["city_freshness"]
    assert "COIMBATORE" in status["city_freshness"]
    assert "HYDERABAD" in status["city_freshness"]


def test_data_monitor_collectors_history():
    resp = client.get("/api/data-monitor/collectors")
    assert resp.status_code == 200
    collectors = resp.json()
    assert isinstance(collectors, list)
