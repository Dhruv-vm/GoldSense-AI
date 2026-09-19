from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.db.session import engine
from ml.training.feature_engineering import add_time_features


OUTPUT_PATH = Path("ml/data/processed/gold_training_dataset.csv")


def load_feature_snapshots() -> pd.DataFrame:
    query = text(
        """
        SELECT
            id,
            observed_at,
            kjpl_gold,
            usdinr,
            xauusd,
            xagusd
        FROM feature_snapshots
        ORDER BY observed_at ASC
        """
    )

    with engine.connect() as connection:
        return pd.read_sql(query, connection)


def load_kjpl_events() -> pd.DataFrame:
    query = text(
        """
        SELECT
            id,
            gold_mjdta,
            source_updated_at
        FROM gold_rates
        WHERE source = 'KJPL'
          AND source_updated_at IS NOT NULL
        ORDER BY source_updated_at ASC
        """
    )

    with engine.connect() as connection:
        return pd.read_sql(query, connection)


def build_event_dataset(
    snapshots: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:

    if snapshots.empty:
        print("[ML] No feature snapshots available.")
        return pd.DataFrame()

    if len(events) < 2:
        print(
            "[ML] Need at least 2 dated KJPL events "
            "to create supervised targets."
        )
        return pd.DataFrame()

    snapshots = snapshots.copy()
    events = events.copy()

    snapshots["observed_at"] = pd.to_datetime(
        snapshots["observed_at"],
        utc=True,
    )

    events["source_updated_at"] = pd.to_datetime(
        events["source_updated_at"],
        utc=True,
    )

    snapshots = snapshots.sort_values("observed_at")
    events = events.sort_values("source_updated_at")

    snapshots = add_time_features(snapshots)

    rows: list[dict] = []

    for i in range(len(events) - 1):
        current_event = events.iloc[i]
        next_event = events.iloc[i + 1]

        current_time = current_event["source_updated_at"]
        next_time = next_event["source_updated_at"]

        # Find the latest market snapshot available
        # at or before the current KJPL publication.
        available = snapshots[
            snapshots["observed_at"] <= current_time
        ]

        if available.empty:
            continue

        feature_row = available.iloc[-1]

        current_price = float(current_event["gold_mjdta"])
        next_price = float(next_event["gold_mjdta"])

        price_change = next_price - current_price

        price_change_pct = (
            (price_change / current_price) * 100
            if current_price != 0
            else None
        )

        if price_change > 0:
            direction = "UP"
        elif price_change < 0:
            direction = "DOWN"
        else:
            direction = "FLAT"

        row = {
            "event_id": int(current_event["id"]),
            "event_time": current_time,
            "next_event_time": next_time,
            "kjpl_gold": current_price,
            "target_gold": next_price,
            "target_change": price_change,
            "target_change_pct": price_change_pct,
            "target_direction": direction,
        }

        # Add all engineered features from the aligned snapshot.
        for column in snapshots.columns:
            if column in {
                "id",
                "observed_at",
                "kjpl_gold",
            }:
                continue

            row[column] = feature_row[column]

        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    print("[ML] Building event-aware training dataset...")

    snapshots = load_feature_snapshots()
    events = load_kjpl_events()

    print(f"[ML] Feature snapshots: {len(snapshots)}")
    print(f"[ML] Dated KJPL events: {len(events)}")

    dataset = build_event_dataset(
        snapshots,
        events,
    )

    if dataset.empty:
        print("[ML] No valid training rows available yet.")
        return

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(f"[ML] Valid training rows: {len(dataset)}")
    print(f"[ML] Saved: {OUTPUT_PATH}")

    print("\n[ML] Target directions:")
    print(
        dataset["target_direction"]
        .value_counts()
        .to_string()
    )

    print("\n[ML] Dataset preview:")
    print(dataset.head().to_string(index=False))


if __name__ == "__main__":
    main()