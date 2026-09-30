from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator


class NewsCategory(str, Enum):
    GOLD_DIRECT = "GOLD_DIRECT"
    GOLD_SUPPLY_DEMAND = "GOLD_SUPPLY_DEMAND"
    GEOPOLITICS = "GEOPOLITICS"
    US_FED_MONETARY_POLICY = "US_FED_MONETARY_POLICY"
    US_MACRO = "US_MACRO"
    US_INFLATION = "US_INFLATION"
    US_LABOR_MARKET = "US_LABOR_MARKET"
    US_DOLLAR = "US_DOLLAR"
    US_TREASURY_YIELDS = "US_TREASURY_YIELDS"
    GLOBAL_FX = "GLOBAL_FX"
    INDIA_RBI = "INDIA_RBI"
    INDIA_MACRO = "INDIA_MACRO"
    INDIA_INFLATION = "INDIA_INFLATION"
    INDIA_FX = "INDIA_FX"
    INDIA_BULLION = "INDIA_BULLION"
    INDIA_GOLD_DEMAND = "INDIA_GOLD_DEMAND"
    INDIA_POLICY = "INDIA_POLICY"
    CHINA_GOLD = "CHINA_GOLD"
    CHINA_MACRO = "CHINA_MACRO"
    CENTRAL_BANK_GOLD = "CENTRAL_BANK_GOLD"
    OIL_ENERGY = "OIL_ENERGY"
    GLOBAL_FINANCIAL_RISK = "GLOBAL_FINANCIAL_RISK"
    GLOBAL_EQUITIES = "GLOBAL_EQUITIES"
    PRECIOUS_METALS = "PRECIOUS_METALS"
    TRADE_TARIFFS = "TRADE_TARIFFS"
    SANCTIONS = "SANCTIONS"
    OTHER = "OTHER"


class NewsArticle(BaseModel):
    title: str
    url: str
    published_at: datetime
    source: str
    language: str | None = None
    description: str | None = None


class SentimentScore(BaseModel):
    positive_probability: float = Field(ge=0.0, le=1.0)
    negative_probability: float = Field(ge=0.0, le=1.0)
    neutral_probability: float = Field(ge=0.0, le=1.0)
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    label: str  # "positive" | "negative" | "neutral"

    @property
    def positive(self) -> float:
        return self.positive_probability

    @property
    def negative(self) -> float:
        return self.negative_probability

    @property
    def neutral(self) -> float:
        return self.neutral_probability


class RelevanceScore(BaseModel):
    gold_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_gold_relevant: bool = False
    primary_category: str = "OTHER"
    supporting_categories: list[str] = Field(default_factory=list)

    # Contextual relevance dimensions (0.0 - 1.0)
    geopolitical_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    india_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    us_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    market_relevance: float = Field(default=0.0, ge=0.0, le=1.0)

    matched_keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def handle_relevance_score_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "relevance_score" in data and "gold_relevance_score" not in data:
                data["gold_relevance_score"] = data["relevance_score"]
        return data

    # Backward compatibility: relevance_score mirrors gold_relevance_score
    @property
    def relevance_score(self) -> float:
        return self.gold_relevance_score


class AnalyzedArticle(BaseModel):
    article: NewsArticle
    sentiment: SentimentScore
    relevance: RelevanceScore

    @property
    def title(self) -> str:
        return self.article.title

    @property
    def url(self) -> str:
        return self.article.url

    @property
    def published_at(self) -> datetime:
        return self.article.published_at

    @property
    def source(self) -> str:
        return self.article.source

    @property
    def sentiment_score(self) -> float:
        return self.sentiment.sentiment_score

    @property
    def sentiment_label(self) -> str:
        return self.sentiment.label

    @property
    def is_gold_relevant(self) -> bool:
        return self.relevance.is_gold_relevant

    @property
    def gold_relevance_score(self) -> float:
        return self.relevance.gold_relevance_score

    @property
    def relevance_score(self) -> float:
        return self.relevance.gold_relevance_score

    @property
    def primary_category(self) -> str:
        return self.relevance.primary_category

    @property
    def supporting_categories(self) -> list[str]:
        return self.relevance.supporting_categories

    @property
    def geopolitical_relevance(self) -> float:
        return self.relevance.geopolitical_relevance

    @property
    def india_relevance(self) -> float:
        return self.relevance.india_relevance

    @property
    def us_relevance(self) -> float:
        return self.relevance.us_relevance

    @property
    def macro_relevance(self) -> float:
        return self.relevance.macro_relevance

    @property
    def market_relevance(self) -> float:
        return self.relevance.market_relevance


class AggregatedSentiment(BaseModel):
    # Time window sentiment means (None if no news in window)
    sentiment_mean_15m: float | None = None
    sentiment_mean_1h: float | None = None
    sentiment_mean_4h: float | None = None
    sentiment_mean_1d: float | None = None

    # Time window news counts
    news_count_15m: int = 0
    news_count_1h: int = 0
    news_count_4h: int = 0
    news_count_1d: int = 0

    # News sentiment ratios over 1d (None if no news in 1d)
    negative_news_ratio: float | None = None
    positive_news_ratio: float | None = None
    neutral_news_ratio: float | None = None

    # Gold specific metrics
    gold_relevant_news_count: int = 0
    gold_sentiment_mean_1d: float | None = None
    gold_relevant_ratio: float | None = None

    # Category-level features (1d window)
    fed_article_count: int = 0
    fed_sentiment_mean: float | None = None
    geopolitical_article_count: int = 0
    geopolitical_sentiment_mean: float | None = None
    india_article_count: int = 0
    india_sentiment_mean: float | None = None
    rbi_article_count: int = 0
    usd_article_count: int = 0
    usd_sentiment_mean: float | None = None
    treasury_article_count: int = 0
    oil_article_count: int = 0
    china_article_count: int = 0
    central_bank_gold_article_count: int = 0
    financial_risk_article_count: int = 0
