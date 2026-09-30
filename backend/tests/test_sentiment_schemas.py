from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.services.sentiment.schemas import (
    AggregatedSentiment,
    AnalyzedArticle,
    NewsArticle,
    RelevanceScore,
    SentimentScore,
)


def test_news_article_schema():
    now = datetime.now(timezone.utc)
    article = NewsArticle(
        title="Gold hits fresh high",
        url="https://example.com/gold-1",
        published_at=now,
        source="example.com",
        language="en",
        description="Gold prices rose sharply on market demand.",
    )
    assert article.title == "Gold hits fresh high"
    assert article.published_at == now
    assert article.source == "example.com"
    assert article.language == "en"


def test_sentiment_score_validation():
    score = SentimentScore(
        positive_probability=0.85,
        negative_probability=0.05,
        neutral_probability=0.10,
        sentiment_score=0.80,
        label="positive",
    )
    assert score.positive == 0.85
    assert score.negative == 0.05
    assert score.neutral == 0.10
    assert score.sentiment_score == 0.80
    assert score.label == "positive"

    # Out of bounds probability should fail
    with pytest.raises(ValidationError):
        SentimentScore(
            positive_probability=1.5,
            negative_probability=0.0,
            neutral_probability=0.0,
            sentiment_score=1.5,
            label="positive",
        )


def test_relevance_score_schema():
    rel = RelevanceScore(
        is_gold_relevant=True,
        relevance_score=0.9,
        matched_keywords=["gold", "bullion"],
    )
    assert rel.is_gold_relevant is True
    assert rel.relevance_score == 0.9
    assert len(rel.matched_keywords) == 2


def test_analyzed_article_schema():
    now = datetime.now(timezone.utc)
    article = NewsArticle(
        title="Gold prices rally",
        url="https://example.com/gold-rally",
        published_at=now,
        source="example.com",
    )
    sentiment = SentimentScore(
        positive_probability=0.9,
        negative_probability=0.05,
        neutral_probability=0.05,
        sentiment_score=0.85,
        label="positive",
    )
    relevance = RelevanceScore(
        is_gold_relevant=True,
        relevance_score=1.0,
        matched_keywords=["gold"],
    )
    analyzed = AnalyzedArticle(
        article=article,
        sentiment=sentiment,
        relevance=relevance,
    )
    assert analyzed.title == "Gold prices rally"
    assert analyzed.sentiment_score == 0.85
    assert analyzed.is_gold_relevant is True
    assert analyzed.gold_relevance_score == 1.0


def test_aggregated_sentiment_defaults():
    agg = AggregatedSentiment()
    assert agg.sentiment_mean_15m is None
    assert agg.sentiment_mean_1h is None
    assert agg.sentiment_mean_4h is None
    assert agg.sentiment_mean_1d is None
    assert agg.news_count_15m == 0
    assert agg.news_count_1h == 0
    assert agg.news_count_4h == 0
    assert agg.news_count_1d == 0
    assert agg.gold_relevant_news_count == 0
    assert agg.negative_news_ratio is None
