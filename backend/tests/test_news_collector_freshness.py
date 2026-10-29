import csv
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from app.services.sentiment.news_client import NewsClient, normalize_title, normalize_url
from app.services.sentiment.schemas import NewsArticle
from app.services.sentiment.live_signal import get_live_news_intelligence


def test_parse_article_stale_rejection():
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    # 28 hours old
    stale_dt = (now - timedelta(hours=28)).strftime("%Y%m%d%H%M%S")
    item = {
        "seendate": stale_dt,
        "title": "Fed announces policy decision",
        "url": "https://example.com/stale-fed",
        "domain": "example.com",
    }
    art = NewsClient._parse_article(
        item,
        max_lookback_hours=24,
        reference_time=now,
    )
    assert art is None


def test_parse_article_future_rejection():
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    # 30 minutes in the future (> 15 min allowance)
    future_dt = (now + timedelta(minutes=30)).strftime("%Y%m%d%H%M%S")
    item = {
        "seendate": future_dt,
        "title": "Future Gold Market Rally",
        "url": "https://example.com/future-gold",
        "domain": "example.com",
    }
    art = NewsClient._parse_article(
        item,
        max_future_minutes=15,
        reference_time=now,
    )
    assert art is None


def test_parse_article_valid_fresh():
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
    # 2 hours old
    fresh_dt = (now - timedelta(hours=2)).strftime("%Y%m%d%H%M%S")
    item = {
        "seendate": fresh_dt,
        "title": "Gold rallies to fresh highs on central bank demand",
        "url": "https://example.com/fresh-gold",
        "domain": "example.com",
        "language": "English",
    }
    art = NewsClient._parse_article(
        item,
        max_lookback_hours=24,
        reference_time=now,
    )
    assert art is not None
    assert art.published_at.tzinfo == timezone.utc
    assert art.title == "Gold rallies to fresh highs on central bank demand"
    assert art.url == "https://example.com/fresh-gold"


def test_parse_article_unparseable_timestamp():
    bad_items = [
        {},
        {"seendate": "not-a-date", "title": "Test"},
        {"seendate": "2026-99-99", "title": "Test"},
        {"seendate": None, "title": "Test"},
        {"seendate": 12345, "title": "Test"},
    ]
    for item in bad_items:
        assert NewsClient._parse_article(item) is None


def test_syndicated_clustering_and_counts():
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)

    # 3 syndicated wire reports of the exact same event
    articles = [
        NewsArticle(
            title="Gold surges as Fed cuts interest rates by 50 basis points - Reuters",
            url="https://reuters.com/markets/commodities/gold-fed-cut-1",
            published_at=now - timedelta(hours=2),
            source="Reuters",
        ),
        NewsArticle(
            title="Gold surges as Fed cuts interest rates by 50 basis points | MarketWatch",
            url="https://marketwatch.com/story/gold-fed-cut-syndicated",
            published_at=now - timedelta(hours=1, minutes=50),
            source="MarketWatch",
        ),
        NewsArticle(
            title="Gold surges as Fed cuts interest rates by 50 basis points",
            url="https://finance.yahoo.com/news/gold-fed-cut-raw",
            published_at=now - timedelta(hours=1, minutes=45),
            source="Yahoo Finance",
        ),
        # Distinct story
        NewsArticle(
            title="Reserve Bank of India increases official gold reserves by 5 tonnes",
            url="https://economictimes.indiatimes.com/rbi-gold-reserves",
            published_at=now - timedelta(hours=3),
            source="The Economic Times",
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "archive.csv"
        live_path = Path(tmpdir) / "live.csv"

        stats = NewsClient.save_news_datasets(
            articles=articles,
            live_csv_path=live_path,
            archive_csv_path=archive_path,
            reference_time=now,
        )

        assert stats["live_count"] == 2  # 1 clustered Fed story + 1 RBI story
        assert live_path.exists()

        with live_path.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) == 2

            # Find clustered story
            fed_cluster = next((r for r in reader if "Fed cuts" in r["title"]), None)
            assert fed_cluster is not None
            assert int(fed_cluster["syndicated_copies_count"]) == 3
            assert fed_cluster["directional_implication"] == "BULLISH"
            assert fed_cluster["driver_category"] == "US_FED_RATES"


def test_live_dataset_isolation_from_archive():
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)

    # Historical batch (5 days ago)
    old_articles = [
        NewsArticle(
            title="Historical Gold Market Commentary From Last Week",
            url="https://example.com/hist-1",
            published_at=now - timedelta(days=5),
            source="Historical Source",
        )
    ]

    # Fresh batch (2 hours ago)
    fresh_articles = [
        NewsArticle(
            title="Gold jumps today as dollar index falls sharply",
            url="https://example.com/fresh-dxy",
            published_at=now - timedelta(hours=2),
            source="Fresh Source",
        )
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "news_articles.csv"
        live_path = Path(tmpdir) / "live_news.csv"

        # First run with old articles
        # (simulate historical data collection)
        NewsClient.save_to_csv(old_articles, archive_path)
        assert len(NewsClient.load_from_csv(archive_path)) == 1

        # Second run with save_news_datasets containing fresh articles
        stats = NewsClient.save_news_datasets(
            articles=fresh_articles,
            live_csv_path=live_path,
            archive_csv_path=archive_path,
            lookback_hours=24,
            max_live_retention_hours=72,
            reference_time=now,
        )

        # Archive MUST retain the historical record plus new record (total 2)
        archive_rows = NewsClient.load_from_csv(archive_path)
        assert len(archive_rows) == 2
        assert any(r.title == "Historical Gold Market Commentary From Last Week" for r in archive_rows)

        # Live dataset MUST contain ONLY the fresh article
        with live_path.open("r", encoding="utf-8") as f:
            live_rows = list(csv.DictReader(f))
            assert len(live_rows) == 1
            assert live_rows[0]["title"] == "Gold jumps today as dollar index falls sharply"
            assert live_rows[0]["ingested_at"] != ""


def test_insufficient_fresh_news_handling():
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)

    # Only 1 fresh story -> insufficient distinct clusters (< 2)
    single_article = [
        NewsArticle(
            title="Gold price today ticks higher",
            url="https://example.com/single-gold",
            published_at=now - timedelta(hours=1),
            source="Single News",
        )
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        live_csv = Path(tmpdir) / "live_news.csv"
        archive_csv = Path(tmpdir) / "archive.csv"

        NewsClient.save_news_datasets(
            articles=single_article,
            live_csv_path=live_csv,
            archive_csv_path=archive_csv,
            reference_time=now,
        )

        intel = get_live_news_intelligence(
            live_csv_path=live_csv,
            reference_time=now,
        )

        assert intel["is_sufficient"] is False
        assert intel["status"] == "INSUFFICIENT_FRESH_RELEVANT_NEWS"
        assert intel["distinct_clusters_count"] == 1


def test_workflow_schedule_ordering():
    project_root = Path(__file__).resolve().parent.parent.parent
    workflows_dir = project_root / ".github" / "workflows"

    news_wf = workflows_dir / "news-collector.yml"
    pipeline_wf = workflows_dir / "pipeline-update.yml"
    market_wf = workflows_dir / "market-collector.yml"

    assert news_wf.exists()
    assert pipeline_wf.exists()
    assert market_wf.exists()

    with news_wf.open("r", encoding="utf-8") as f:
        news_content = yaml.safe_load(f)
    with pipeline_wf.open("r", encoding="utf-8") as f:
        pipeline_content = yaml.safe_load(f)
    with market_wf.open("r", encoding="utf-8") as f:
        market_content = yaml.safe_load(f)

    def get_schedule(content):
        on_clause = content.get(True) or content.get("on")
        return on_clause.get("schedule", [])

    # 1. Check pipeline-update runs after news collector evening batch (15:00 UTC)
    pipeline_crons = [c["cron"] for c in get_schedule(pipeline_content)]
    assert "38 15 * * *" in pipeline_crons, (
        f"Pipeline update cron {pipeline_crons} must be '38 15 * * *' (15:38 UTC = 09:08 PM IST) "
        "to run strictly after the 15:00 UTC news batch."
    )

    # 2. Check news collector cron schedule
    news_crons = [c["cron"] for c in get_schedule(news_content)]
    assert "0 3,9,15,21 * * *" in news_crons

    # 3. Verify market collector does not have unsupported 'timezone' field under cron
    for cron_entry in get_schedule(market_content):
        assert "timezone" not in cron_entry, (
            "GitHub Actions cron does not support 'timezone' under schedule list. Must be UTC only."
        )
