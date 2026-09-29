from __future__ import annotations

from pathlib import Path

import pandas as pd


KJPL_PATH = Path(
    "backend/ml/data/processed/kjpl_events.csv"
)

MARKET_PATH = Path(
    "backend/ml/data/processed/market_features.csv"
)

OUTPUT_PATH = Path(
    "backend/ml/data/processed/gold_training_dataset.csv"
)


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

    df = (
        df.sort_values("event_time")
        .reset_index(drop=True)
    )

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


def align_market_to_kjpl(
    kjpl: pd.DataFrame,
    market: pd.DataFrame,
) -> pd.DataFrame:

    # IMPORTANT:
    #
    # For every KJPL event, use ONLY market data
    # available at or before that KJPL event.
    #
    # This prevents future-data leakage.

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
        column
        for column in market_columns
        if column in market.columns
    ]

    market_subset = market[
        available_columns
    ].copy()

    market_subset = market_subset.rename(
        columns={
            "observed_at": "market_observed_at"
        }
    )

    aligned = pd.merge_asof(
        kjpl.sort_values("event_time"),
        market_subset.sort_values(
            "market_observed_at"
        ),
        left_on="event_time",
        right_on="market_observed_at",
        direction="backward",
    )

    return aligned


def add_kjpl_features(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = df.copy()

    # KJPL gold's own recent movement.
    result["kjpl_gold_change"] = (
        result["gold_mjdta"]
        - result["gold_mjdta"].shift(1)
    )

    result["kjpl_gold_change_pct"] = (
        result["gold_mjdta"]
        .pct_change()
        * 100
    )

    # Silver movement.
    result["kjpl_silver_change"] = (
        result["silver_mjdta"]
        - result["silver_mjdta"].shift(1)
    )

    result["kjpl_silver_change_pct"] = (
        result["silver_mjdta"]
        .pct_change()
        * 100
    )

    # Difference between KJPL gold and
    # international gold converted to INR/gram.
    result["kjpl_global_premium_inr"] = (
        result["gold_mjdta"]
        - result["gold_global_inr_per_gram"]
    )

    result["kjpl_global_premium_pct"] = (
        (
            result["gold_mjdta"]
            - result["gold_global_inr_per_gram"]
        )
        / result["gold_global_inr_per_gram"]
        * 100
    )

    # KJPL/global ratio.
    result["kjpl_global_ratio"] = (
        result["gold_mjdta"]
        / result["gold_global_inr_per_gram"]
    )

    return result


def remove_unusable_targets(
    df: pd.DataFrame,
) -> pd.DataFrame:

    # The latest KJPL event has no next event.
    # It is useful for live prediction but cannot
    # be used as a supervised training row.

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

    print(
        f"[DATASET] KJPL events: {len(kjpl)}"
    )

    print("[DATASET] Loading market features...")

    market = load_market_features()

    print(
        f"[DATASET] Market observations: "
        f"{len(market)}"
    )

    print(
        "[DATASET] Aligning market data "
        "to KJPL events..."
    )

    dataset = align_market_to_kjpl(
        kjpl,
        market,
    )

    dataset = add_kjpl_features(
        dataset
    )

    training_dataset = remove_unusable_targets(
        dataset
    )

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    training_dataset.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        f"\n[DATASET] Training rows: "
        f"{len(training_dataset)}"
    )

    print(
        f"[DATASET] Saved to: "
        f"{OUTPUT_PATH}"
    )

    print("\n[DATASET] Target distribution:")

    print(
        training_dataset[
            "target_direction"
        ].value_counts()
    )

    print(
        "\n[DATASET] Preview:"
    )

    preview_columns = [
        "event_time",
        "gold_mjdta",
        "market_observed_at",
        "xauusd",
        "usdinr",
        "gold_global_inr_per_gram",
        "kjpl_global_premium_pct",
        "next_event_time",
        "next_event_gold",
        "target_change",
        "target_change_pct",
        "target_direction",
    ]

    available_preview = [
        column
        for column in preview_columns
        if column in training_dataset.columns
    ]

    print(
        training_dataset[
            available_preview
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()