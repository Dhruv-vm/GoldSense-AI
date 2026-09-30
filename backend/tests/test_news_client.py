import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from app.services.sentiment.news_client import NewsClient, normalize_title, normalize_url
from app.services.sentiment.schemas import NewsArticle


# 28. Timezone-aware timestamp
def test_parse_article_timezone_aware():
    raw_item = {
        "seendate": "20260928T093100Z",
        "title": "Gold rate today in Mumbai",
        "url": "https://example.com/gold-today",
        "domain": "example.com",
        "language": "English",
    }
    article = NewsClient._parse_article(raw_item)
    assert article is not None
    assert article.published_at.tzinfo == timezone.utc
    assert article.published_at == datetime(2026, 9, 28, 9, 31, 0, tzinfo=timezone.utc)
    assert article.title == "Gold rate today in Mumbai"
    assert article.url == "https://example.com/gold-today"
    assert article.source == "example.com"


def test_parse_invalid_article():
    assert NewsClient._parse_article({}) is None
    assert NewsClient._parse_article({"seendate": "invalid"}) is None
    assert NewsClient._parse_article({"seendate": "20260928T093100Z", "title": ""}) is None


# 26. Duplicate URL -> deduplicated
def test_duplicate_url_deduplicated():
    raw_url_1 = "https://example.com/markets/gold-surge?utm_source=twitter&utm_medium=social"
    raw_url_2 = "https://example.com/markets/gold-surge/?oc=5"
    assert normalize_url(raw_url_1) == normalize_url(raw_url_2)

    art1 = NewsArticle(
        title="Gold surges on rate cut expectations",
        url=raw_url_1,
        published_at=datetime.now(timezone.utc),
        source="example.com",
    )
    art2 = NewsArticle(
        title="Gold surges on rate cut expectations",
        url=raw_url_2,
        published_at=datetime.now(timezone.utc),
        source="example.com",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "news.csv"
        added1 = NewsClient.save_to_csv([art1], csv_path)
        added2 = NewsClient.save_to_csv([art2], csv_path)
        assert added1 == 1
        assert added2 == 0  # Deduplicated!
        assert len(NewsClient.load_from_csv(csv_path)) == 1


# 27. Duplicate normalized title -> deduplicated
def test_duplicate_normalized_title_deduplicated():
    title1 = "Gold prices tumble amid strong US dollar - Reuters"
    title2 = "Gold prices tumble amid strong US dollar | MarketWatch"
    assert normalize_title(title1) == normalize_title(title2)

    art1 = NewsArticle(
        title=title1,
        url="https://reuters.com/gold-1",
        published_at=datetime.now(timezone.utc),
        source="reuters.com",
    )
    art2 = NewsArticle(
        title=title2,
        url="https://marketwatch.com/gold-syndicated",
        published_at=datetime.now(timezone.utc),
        source="marketwatch.com",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "news.csv"
        added1 = NewsClient.save_to_csv([art1], csv_path)
        added2 = NewsClient.save_to_csv([art2], csv_path)
        assert added1 == 1
        assert added2 == 0  # Same story, deduplicated by normalized title!
        assert len(NewsClient.load_from_csv(csv_path)) == 1


# 31. GDELT HTTP 429 -> retry
def test_gdelt_http_429_retry():
    client = NewsClient(timeout=5, max_retries=3, retry_wait_seconds=1)

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "articles": [
            {
                "seendate": "20260928T100000Z",
                "title": "Gold steadies in Asia",
                "url": "https://example.com/gold-steady",
                "domain": "example.com",
            }
        ]
    }

    # First attempt: 429, second attempt: 200
    with patch.object(client.session, "get", side_effect=[mock_resp_429, mock_resp_200]) as mock_get:
        with patch("time.sleep") as mock_sleep:
            articles = client.search(query="gold", max_records=5, enable_fallback=False)
            assert len(articles) == 1
            assert mock_get.call_count == 2
            mock_sleep.assert_called_once_with(8)


# 32. GDELT failure -> RSS fallback
def test_gdelt_failure_triggers_rss_fallback():
    client = NewsClient(timeout=5, max_retries=3, retry_wait_seconds=1)

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429

    fallback_articles = [
        NewsArticle(
            title="Gold rebounds on festive demand",
            url="https://example.com/rss-gold",
            published_at=datetime.now(timezone.utc),
            source="RSS News",
        )
    ]

    with patch.object(client.session, "get", return_value=mock_resp_429):
        with patch("time.sleep"):
            with patch.object(client, "search_rss", return_value=fallback_articles) as mock_rss:
                articles = client.search(query="gold", max_records=5, enable_fallback=True)
                assert len(articles) == 1
                assert articles[0].title == "Gold rebounds on festive demand"
                mock_rss.assert_called_once()
