import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_PATH = PROJECT_ROOT / "backend/ml/data/processed/gold_training_dataset.csv"
KJPL_PATH = PROJECT_ROOT / "backend/ml/data/processed/kjpl_events.csv"


def test_processed_dataset_integrity():
    assert DATASET_PATH.exists(), f"Dataset not found at {DATASET_PATH}"
    df = pd.read_csv(DATASET_PATH)

    # 1. Row count: Exactly 10 supervised rows (from 11 KJPL events)
    assert len(df) == 10

    # 2. Key targets must be present
    assert "target_change" in df.columns
    assert "target_direction" in df.columns
    assert "next_event_gold" in df.columns
    assert df["target_change"].notna().all()
    assert df["target_direction"].isin(["UP", "DOWN", "FLAT"]).all()

    # 3. Sentiment feature columns must exist
    expected_sentiment_cols = [
        "sentiment_mean_15m",
        "sentiment_mean_1h",
        "sentiment_mean_4h",
        "sentiment_mean_1d",
        "news_count_15m",
        "news_count_1h",
        "news_count_4h",
        "news_count_1d",
        "positive_news_ratio",
        "negative_news_ratio",
        "neutral_news_ratio",
        "gold_relevant_news_count",
        "gold_sentiment_mean_1d",
    ]
    for col in expected_sentiment_cols:
        assert col in df.columns, f"Missing sentiment column: {col}"

    # 4. Strict no-lookahead: verify chronological order
    event_times = pd.to_datetime(df["event_time"], utc=True)
    assert event_times.is_monotonic_increasing

    # 5. Market observed time <= event time
    market_times = pd.to_datetime(df["market_observed_at"].dropna(), utc=True)
    event_times_subset = event_times[df["market_observed_at"].notna()]
    assert (market_times <= event_times_subset).all()


def test_last_event_excluded_from_training():
    """
    Ensure the most recent event (which has no target) is never in gold_training_dataset.csv
    """
    kjpl_df = pd.read_csv(KJPL_PATH)
    last_event_id = kjpl_df["event_id"].max()

    df = pd.read_csv(DATASET_PATH)
    assert last_event_id not in df["event_id"].values
