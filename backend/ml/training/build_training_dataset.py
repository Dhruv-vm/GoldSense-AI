from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Add backend directory to sys.path to enable app module imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.sentiment.aggregator import SentimentAggregator
from app.services.sentiment.analyzer import SentimentAnalyzer
from app.services.sentiment.news_client import NewsClient
from app.services.sentiment.schemas import (
    AnalyzedArticle,
    NewsArticle,
    RelevanceScore,
    SentimentScore,
)

KJPL_PATH = PROJECT_ROOT / "backend/ml/data/processed/kjpl_events.csv"
MARKET_PATH = PROJECT_ROOT / "backend/ml/data/processed/market_features.csv"
NEWS_RAW_PATH = PROJECT_ROOT / "data/news/news_articles.csv"
NEWS_ANALYZED_PATH = PROJECT_ROOT / "backend/ml/data/processed/analyzed_news.csv"
OUTPUT_PATH = PROJECT_ROOT / "backend/ml/data/processed/gold_training_dataset.csv"


def load_kjpl_events() -> pd.DataFrame:
    df = pd.read_csv(KJPL_PATH)

    df["event_time"] = pd.to_datetime(
        df["event_time"],
        utc=True,
        errors="coerce",
    )

    numeric_columns = [
        "gold_mjdta",
        "silver_mjdta",
        "next_event_gold",
        "target_change",
        "target_change_pct",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    df = df.sort_values("event_time").reset_index(drop=True)
    return df


def load_market_features() -> pd.DataFrame:
    df = pd.read_csv(MARKET_PATH)

    df["observed_at"] = pd.to_datetime(
        df["observed_at"],
        utc=True,
        errors="coerce",
    )

    df = (
        df.dropna(subset=["observed_at"])
        .sort_values("observed_at")
        .reset_index(drop=True)
    )

    return df


def load_or_analyze_news() -> list[AnalyzedArticle]:
    """
    Load pre-analyzed news from CSV cache if available;
    otherwise load raw news articles, analyze them via SentimentAnalyzer,
    and cache the analyzed results to CSV.
    """
    if NEWS_ANALYZED_PATH.exists():
        print(f"[SENTIMENT] Loading pre-analyzed news from {NEWS_ANALYZED_PATH}...")
        df_analyzed = pd.read_csv(NEWS_ANALYZED_PATH)
        df_analyzed["published_at"] = pd.to_datetime(df_analyzed["published_at"], utc=True)

        articles: list[AnalyzedArticle] = []
        for _, row in df_analyzed.iterrows():
            article = NewsArticle(
                title=str(row["title"]),
                url=str(row["url"]),
                published_at=row["published_at"].to_pydatetime(),
                source=str(row["source"]),
                language=str(row["language"]) if pd.notna(row.get("language")) else None,
            )
            sentiment = SentimentScore(
                positive_probability=float(row["positive_probability"]),
                negative_probability=float(row["negative_probability"]),
                neutral_probability=float(row["neutral_probability"]),
                sentiment_score=float(row["sentiment_score"]),
                label=str(row["sentiment_label"]),
            )
            supporting_raw = str(row.get("supporting_categories", ""))
            supporting_list = [c.strip() for c in supporting_raw.split(";") if c.strip()] if pd.notna(supporting_raw) else []

            relevance = RelevanceScore(
                gold_relevance_score=float(row.get("gold_relevance_score", 0.0)),
                is_gold_relevant=bool(row.get("is_gold_relevant", False)),
                primary_category=str(row.get("primary_category", "OTHER")),
                supporting_categories=supporting_list,
                geopolitical_relevance=float(row.get("geopolitical_relevance", 0.0)),
                india_relevance=float(row.get("india_relevance", 0.0)),
                us_relevance=float(row.get("us_relevance", 0.0)),
                macro_relevance=float(row.get("macro_relevance", 0.0)),
                market_relevance=float(row.get("market_relevance", 0.0)),
                matched_keywords=[],
            )
            articles.append(
                AnalyzedArticle(
                    article=article,
                    sentiment=sentiment,
                    relevance=relevance,
                )
            )
        print(f"[SENTIMENT] Loaded {len(articles)} analyzed articles.")
        return articles

    if not NEWS_RAW_PATH.exists():
        print(f"[SENTIMENT] No news data found at {NEWS_RAW_PATH}. Proceeding with empty news.")
        return []

    print(f"[SENTIMENT] Loading raw news from {NEWS_RAW_PATH}...")
    raw_articles = NewsClient.load_from_csv(NEWS_RAW_PATH)
    if not raw_articles:
        print("[SENTIMENT] No raw articles found in CSV.")
        return []

    print(f"[SENTIMENT] Analyzing {len(raw_articles)} articles with FinBERT...")
    analyzer = SentimentAnalyzer()
    analyzed_articles = analyzer.analyze_articles(raw_articles)

    # Save to analyzed cache
    NEWS_ANALYZED_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache_rows: list[dict] = []
    for a in analyzed_articles:
        cache_rows.append(
            {
                "published_at": a.published_at.isoformat(),
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "language": a.article.language or "",
                "positive_probability": a.sentiment.positive_probability,
                "negative_probability": a.sentiment.negative_probability,
                "neutral_probability": a.sentiment.neutral_probability,
                "sentiment_score": a.sentiment_score,
                "sentiment_label": a.sentiment_label,
                "is_gold_relevant": a.is_gold_relevant,
                "gold_relevance_score": a.gold_relevance_score,
                "primary_category": a.primary_category,
                "supporting_categories": ";".join(a.supporting_categories),
                "geopolitical_relevance": a.geopolitical_relevance,
                "india_relevance": a.india_relevance,
                "us_relevance": a.us_relevance,
                "macro_relevance": a.macro_relevance,
                "market_relevance": a.market_relevance,
            }
        )
    pd.DataFrame(cache_rows).to_csv(NEWS_ANALYZED_PATH, index=False)
    print(f"[SENTIMENT] Saved analyzed news cache to {NEWS_ANALYZED_PATH}")

    return analyzed_articles


def align_market_to_kjpl(
    kjpl: pd.DataFrame,
    market: pd.DataFrame,
) -> pd.DataFrame:
    """
    For every KJPL event, use ONLY market data available at or before
    that KJPL event (market_observed_at <= event_time).
    """
    market_columns = [
        "observed_at",
        "usdinr",
        "xauusd",
        "xagusd",
        "usdinr_return_15m",
        "xauusd_return_15m",
        "xagusd_return_15m",
        "usdinr_return_1h",
        "xauusd_return_1h",
        "xagusd_return_1h",
        "usdinr_return_4h",
        "xauusd_return_4h",
        "xagusd_return_4h",
        "usdinr_return_1d",
        "xauusd_return_1d",
        "xagusd_return_1d",
        "gold_global_inr_per_gram",
        "silver_global_inr_per_gram",
        "gold_silver_ratio",
        "hour",
        "minute",
        "day_of_week",
        "is_weekend",
        "is_monday",
        "is_friday",
        "observation_gap_minutes",
        "market_stale",
    ]

    available_columns = [
        col for col in market_columns if col in market.columns
    ]

    market_subset = market[available_columns].copy()
    market_subset = market_subset.rename(
        columns={"observed_at": "market_observed_at"}
    )

    aligned = pd.merge_asof(
        kjpl.sort_values("event_time"),
        market_subset.sort_values("market_observed_at"),
        left_on="event_time",
        right_on="market_observed_at",
        direction="backward",
    )

    return aligned


def add_kjpl_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    # KJPL gold's own recent movement
    result["kjpl_gold_change"] = (
        result["gold_mjdta"] - result["gold_mjdta"].shift(1)
    )
    result["kjpl_gold_change_pct"] = (
        result["gold_mjdta"].pct_change() * 100
    )

    # Silver movement
    result["kjpl_silver_change"] = (
        result["silver_mjdta"] - result["silver_mjdta"].shift(1)
    )
    result["kjpl_silver_change_pct"] = (
        result["silver_mjdta"].pct_change() * 100
    )

    # Difference between KJPL gold and international gold converted to INR/gram
    result["kjpl_global_premium_inr"] = (
        result["gold_mjdta"] - result["gold_global_inr_per_gram"]
    )
    result["kjpl_global_premium_pct"] = (
        (result["gold_mjdta"] - result["gold_global_inr_per_gram"])
        / result["gold_global_inr_per_gram"]
        * 100
    )

    # KJPL/global ratio
    result["kjpl_global_ratio"] = (
        result["gold_mjdta"] / result["gold_global_inr_per_gram"]
    )

    return result


def add_sentiment_features(
    df: pd.DataFrame,
    analyzed_articles: list[AnalyzedArticle],
) -> pd.DataFrame:
    """
    Aggregate sentiment features strictly with no lookahead.
    For each event at event_time T:
        feature_time <= T
    Any news published after T is excluded.
    """
    result = df.copy()
    aggregator = SentimentAggregator()

    sentiment_features_df = aggregator.aggregate_for_events(
        events_df=result,
        analyzed_articles=analyzed_articles,
        time_col="event_time",
    )

    for col in sentiment_features_df.columns:
        result[col] = sentiment_features_df[col].values

    return result


def remove_unusable_targets(df: pd.DataFrame) -> pd.DataFrame:
    """
    The latest KJPL event has no next event.
    It is useful for live prediction but cannot be used as a supervised training row.
    """
    result = df.dropna(
        subset=[
            "next_event_gold",
            "target_change",
            "target_change_pct",
        ]
    ).copy()

    return result


def main() -> None:
    print("[DATASET] Loading KJPL events...")
    kjpl = load_kjpl_events()
    print(f"[DATASET] KJPL events: {len(kjpl)}")

    print("[DATASET] Loading market features...")
    market = load_market_features()
    print(f"[DATASET] Market observations: {len(market)}")

    print("[DATASET] Loading / analyzing news sentiment...")
    analyzed_news = load_or_analyze_news()
    print(f"[DATASET] Total available analyzed news: {len(analyzed_news)}")

    print("[DATASET] Aligning market data to KJPL events...")
    dataset = align_market_to_kjpl(kjpl, market)

    print("[DATASET] Adding KJPL features...")
    dataset = add_kjpl_features(dataset)

    print("[DATASET] Adding no-lookahead sentiment features...")
    dataset = add_sentiment_features(dataset, analyzed_news)

    training_dataset = remove_unusable_targets(dataset)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    training_dataset.to_csv(OUTPUT_PATH, index=False)

    print(f"\n[DATASET] Training rows: {len(training_dataset)}")
    print(f"[DATASET] Saved to: {OUTPUT_PATH}")

    print("\n[DATASET] Target distribution:")
    print(training_dataset["target_direction"].value_counts())

    print("\n[DATASET] Preview of sentiment features:")
    sentiment_cols = [
        "event_time",
        "gold_mjdta",
        "target_direction",
        "news_count_1d",
        "sentiment_mean_1d",
        "positive_news_ratio",
        "negative_news_ratio",
        "neutral_news_ratio",
        "gold_relevant_news_count",
        "gold_sentiment_mean_1d",
    ]
    available_sentiment_cols = [
        c for c in sentiment_cols if c in training_dataset.columns
    ]
    print(training_dataset[available_sentiment_cols].to_string(index=False))


if __name__ == "__main__":
    main()