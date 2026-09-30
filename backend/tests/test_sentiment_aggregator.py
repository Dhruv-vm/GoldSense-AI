from datetime import datetime, timedelta, timezone

from app.services.sentiment.aggregator import SentimentAggregator
from app.services.sentiment.schemas import (
    AnalyzedArticle,
    NewsArticle,
    RelevanceScore,
    SentimentScore,
)


def make_analyzed_article(
    title: str,
    published_at: datetime,
    score: float,
    label: str,
    is_gold: bool = True,
) -> AnalyzedArticle:
    pos = max(0.0, score) if score > 0 else 0.1
    neg = max(0.0, -score) if score < 0 else 0.1
    neu = max(0.0, 1.0 - pos - neg)
    return AnalyzedArticle(
        article=NewsArticle(
            title=title,
            url=f"https://example.com/{title.replace(' ', '-').lower()}",
            published_at=published_at,
            source="example.com",
        ),
        sentiment=SentimentScore(
            positive_probability=pos,
            negative_probability=neg,
            neutral_probability=neu,
            sentiment_score=score,
            label=label,
        ),
        relevance=RelevanceScore(
            is_gold_relevant=is_gold,
            relevance_score=1.0 if is_gold else 0.0,
            matched_keywords=["gold"] if is_gold else [],
        ),
    )


def test_strict_no_lookahead():
    """
    CRITICAL TEST: Ensure news published after the cutoff time NEVER
    enters the aggregated features for that timestamp.
    """
    event_time = datetime(2026, 9, 28, 9, 31, tzinfo=timezone.utc)
    aggregator = SentimentAggregator()

    # Article 1: 10 minutes BEFORE event
    art_past = make_analyzed_article(
        "Gold slips before market open",
        event_time - timedelta(minutes=10),
        score=-0.5,
        label="negative",
    )
    # Article 2: exactly AT event time
    art_exact = make_analyzed_article(
        "Gold price published",
        event_time,
        score=0.1,
        label="positive",
    )
    # Article 3: 1 minute AFTER event (future news!)
    art_future_1m = make_analyzed_article(
        "Gold plunges unexpectedly in afternoon",
        event_time + timedelta(minutes=1),
        score=-0.9,
        label="negative",
    )
    # Article 4: 2 hours AFTER event (future news!)
    art_future_2h = make_analyzed_article(
        "Evening gold wrap",
        event_time + timedelta(hours=2),
        score=0.8,
        label="positive",
    )

    all_articles = [art_past, art_exact, art_future_1m, art_future_2h]

    agg = aggregator.aggregate_for_timestamp(all_articles, event_time)

    # Only art_past and art_exact can be included!
    assert agg.news_count_15m == 2
    assert agg.news_count_1h == 2
    assert agg.news_count_1d == 2

    # Verify that future news was strictly excluded from mean
    expected_mean = round((-0.5 + 0.1) / 2, 4)
    assert agg.sentiment_mean_15m == expected_mean
    assert agg.sentiment_mean_1d == expected_mean


def test_missing_history_remains_none():
    """
    Ensure that windows with no news return None (not 0.0),
    so missing market/news data is not conflated with neutral sentiment.
    """
    event_time = datetime(2026, 9, 28, 9, 31, tzinfo=timezone.utc)
    aggregator = SentimentAggregator()

    # Article published 6 hours before event
    art = make_analyzed_article(
        "Early morning gold report",
        event_time - timedelta(hours=6),
        score=0.4,
        label="positive",
    )

    agg = aggregator.aggregate_for_timestamp([art], event_time)

    # 15m, 1h, 4h windows have NO news -> MUST BE NONE
    assert agg.news_count_15m == 0
    assert agg.sentiment_mean_15m is None
    assert agg.news_count_1h == 0
    assert agg.sentiment_mean_1h is None
    assert agg.news_count_4h == 0
    assert agg.sentiment_mean_4h is None

    # 1d window HAS the 6h-old article
    assert agg.news_count_1d == 1
    assert agg.sentiment_mean_1d == 0.4


def test_sentiment_ratios_and_gold_relevance():
    event_time = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    aggregator = SentimentAggregator()

    articles = [
        make_analyzed_article("Gold up", event_time - timedelta(hours=2), 0.6, "positive", is_gold=True),
        make_analyzed_article("Gold down", event_time - timedelta(hours=3), -0.8, "negative", is_gold=True),
        make_analyzed_article("Tech rally", event_time - timedelta(hours=5), 0.5, "positive", is_gold=False),
        make_analyzed_article("Market flat", event_time - timedelta(hours=8), 0.0, "neutral", is_gold=False),
    ]

    agg = aggregator.aggregate_for_timestamp(articles, event_time)

    assert agg.news_count_1d == 4
    # 2 positive, 1 negative, 1 neutral out of 4 total
    assert agg.positive_news_ratio == 0.50
    assert agg.negative_news_ratio == 0.25
    assert agg.neutral_news_ratio == 0.25

    # 2 gold-relevant articles
    assert agg.gold_relevant_news_count == 2
    assert agg.gold_relevant_ratio == 0.50
    # Gold sentiment mean = (0.6 + (-0.8)) / 2 = -0.1
    assert agg.gold_sentiment_mean_1d == -0.10
