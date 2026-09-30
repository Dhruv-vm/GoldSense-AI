from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.sentiment.aggregator import SentimentAggregator
    from app.services.sentiment.analyzer import SentimentAnalyzer
    from app.services.sentiment.news_client import NewsClient
    from app.services.sentiment.relevance import GoldRelevanceScorer
    from app.services.sentiment.schemas import (
        AggregatedSentiment,
        AnalyzedArticle,
        NewsArticle,
        RelevanceScore,
        SentimentScore,
    )

__all__ = [
    "NewsClient",
    "SentimentAnalyzer",
    "GoldRelevanceScorer",
    "SentimentAggregator",
    "NewsArticle",
    "SentimentScore",
    "RelevanceScore",
    "AnalyzedArticle",
    "AggregatedSentiment",
]


def __getattr__(name: str) -> Any:
    if name == "NewsClient":
        from app.services.sentiment.news_client import NewsClient
        return NewsClient
    if name == "SentimentAnalyzer":
        from app.services.sentiment.analyzer import SentimentAnalyzer
        return SentimentAnalyzer
    if name == "GoldRelevanceScorer":
        from app.services.sentiment.relevance import GoldRelevanceScorer
        return GoldRelevanceScorer
    if name == "SentimentAggregator":
        from app.services.sentiment.aggregator import SentimentAggregator
        return SentimentAggregator
    if name in (
        "AggregatedSentiment",
        "AnalyzedArticle",
        "NewsArticle",
        "RelevanceScore",
        "SentimentScore",
    ):
        from app.services.sentiment import schemas
        return getattr(schemas, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
