import pytest
from app.services.sentiment.analyzer import SentimentAnalyzer
from app.services.sentiment.schemas import NewsArticle
from datetime import datetime, timezone


@pytest.fixture(scope="module")
def analyzer():
    return SentimentAnalyzer()


def test_positive_financial_sentiment(analyzer):
    text = "Gold prices surge to historic high on massive investor demand"
    score = analyzer.analyze_text(text)
    assert score.label == "positive"
    assert score.sentiment_score > 0.0
    assert score.positive_probability > score.negative_probability
    assert 0.0 <= score.positive_probability <= 1.0


def test_negative_financial_sentiment(analyzer):
    text = "Gold plunges sharply as heavy selloff hits bullion markets"
    score = analyzer.analyze_text(text)
    assert score.label == "negative"
    assert score.sentiment_score < 0.0
    assert score.negative_probability > score.positive_probability
    assert 0.0 <= score.negative_probability <= 1.0


def test_batch_analyze_articles(analyzer):
    articles = [
        NewsArticle(
            title="Gold rallies to fresh records",
            url="https://example.com/1",
            published_at=datetime.now(timezone.utc),
            source="example.com",
        ),
        NewsArticle(
            title="Gold crashes amidst market panic",
            url="https://example.com/2",
            published_at=datetime.now(timezone.utc),
            source="example.com",
        ),
    ]
    results = analyzer.analyze_articles(articles)
    assert len(results) == 2
    assert results[0].sentiment_label == "positive"
    assert results[1].sentiment_label == "negative"
    assert results[0].is_gold_relevant is True
    assert results[1].is_gold_relevant is True
