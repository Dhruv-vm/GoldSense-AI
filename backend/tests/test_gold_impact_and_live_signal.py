from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services.sentiment.gold_impact import (
    GoldDriver,
    evaluate_gold_impact,
    extract_cluster_key,
)
from app.services.sentiment.live_signal import (
    get_live_news_intelligence,
    parse_utc_timestamp,
)

client = TestClient(app)


def test_cluster_key_normalizes_syndicated_headlines():
    t1 = "Fed Holds Interest Rates Steady Amid Inflation Worries - Reuters"
    t2 = "Fed Holds Interest Rates Steady Amid Inflation Worries - Bloomberg"
    t3 = "Fed Holds Interest Rates Steady Amid Inflation Worries | Financial Times"
    k1 = extract_cluster_key(t1)
    k2 = extract_cluster_key(t2)
    k3 = extract_cluster_key(t3)
    assert k1 == k2 == k3
    assert "reuters" not in k1
    assert "bloomberg" not in k2


def test_gold_impact_hawkish_fed_is_bearish():
    ref_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    pub_time = ref_time - timedelta(hours=2)
    res = evaluate_gold_impact(
        title="Fed favors rate hikes as bond yields surge",
        published_at=pub_time,
        reference_time=ref_time,
    )
    assert res["driver_category"] == GoldDriver.US_FED_RATES
    assert res["directional_implication"] == "BEARISH"
    assert res["confidence"] == "HIGH"
    assert "opportunity cost" in res["evidence_rationale"].lower()


def test_gold_impact_dovish_fed_is_bullish():
    ref_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    pub_time = ref_time - timedelta(hours=3)
    res = evaluate_gold_impact(
        title="Gold rallies as Fed pauses and rate cuts expected",
        published_at=pub_time,
        reference_time=ref_time,
    )
    assert res["driver_category"] in (GoldDriver.US_FED_RATES, GoldDriver.MARKET_MOMENTUM)
    assert res["directional_implication"] == "BULLISH"
    assert res["confidence"] in ("HIGH", "MEDIUM")


def test_gold_impact_strong_dollar_is_bearish():
    ref_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    pub_time = ref_time - timedelta(hours=1)
    res = evaluate_gold_impact(
        title="Dollar strengthens as DXY climbs to multi-month peak",
        published_at=pub_time,
        reference_time=ref_time,
    )
    assert res["driver_category"] == GoldDriver.US_DOLLAR_FX
    assert res["directional_implication"] == "BEARISH"
    assert "acquisition cost" in res["evidence_rationale"].lower()


def test_gold_impact_geopolitics_and_safe_haven_is_bullish():
    ref_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    pub_time = ref_time - timedelta(hours=4)
    res = evaluate_gold_impact(
        title="Gold safe-haven demand surges as military conflict escalates",
        published_at=pub_time,
        reference_time=ref_time,
    )
    assert res["driver_category"] == GoldDriver.GEOPOLITICS_SAFE_HAVEN
    assert res["directional_implication"] == "BULLISH"
    assert res["confidence"] == "HIGH"


def test_gold_impact_central_bank_buying_is_bullish():
    ref_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    pub_time = ref_time - timedelta(hours=5)
    res = evaluate_gold_impact(
        title="Central bank gold buying hits fresh high as PBOC reserves jump",
        published_at=pub_time,
        reference_time=ref_time,
    )
    assert res["driver_category"] == GoldDriver.PHYSICAL_AND_CENTRAL_BANK
    assert res["directional_implication"] == "BULLISH"
    assert "physical" in res["evidence_rationale"].lower()


def test_timestamp_parser_utilities():
    assert parse_utc_timestamp("") is None
    assert parse_utc_timestamp("   ") is None
    dt1 = parse_utc_timestamp("2026-10-29T08:30:00+00:00")
    assert dt1 is not None and dt1.hour == 8
    dt2 = parse_utc_timestamp("2026-10-29 08:30:00")
    assert dt2 is not None and dt2.tzinfo == timezone.utc


def test_live_news_intelligence_insufficient_fresh_news():
    # Set reference time way ahead so that existing corpus is older than 24h
    far_future = datetime(2028, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = get_live_news_intelligence(window_hours=24, reference_time=far_future)
    assert res["status"] == "INSUFFICIENT_FRESH_RELEVANT_NEWS"
    assert res["distinct_clusters_count"] == 0
    assert "At least 2 distinct clusters" in res["message"]


def test_live_news_signal_api_endpoint():
    res = client.get("/api/news/live-signal?window_hours=24")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "window_hours" in data
    assert data["window_hours"] == 24
    assert "distinct_clusters_count" in data
    assert "net_signal" in data
    assert "market_vs_news_alignment" in data
    assert "representative_articles" in data
    assert isinstance(data["representative_articles"], list)


def test_news_latest_endpoint_with_window():
    res = client.get("/api/news/latest?window_hours=24&limit=10")
    assert res.status_code == 200
    articles = res.json()
    assert isinstance(articles, list)
    for art in articles:
        assert "driver_category" in art
        assert "directional_implication" in art
        assert "confidence" in art
        assert "evidence_rationale" in art
        assert "age_display" in art


def test_prediction_status_includes_news_intelligence():
    res = client.get("/api/predictions/latest")
    assert res.status_code == 200
    data = res.json()
    assert "news_intelligence" in data
    news_intel = data["news_intelligence"]
    assert "status" in news_intel
    assert "net_signal" in news_intel
    assert "market_vs_news_alignment" in news_intel
