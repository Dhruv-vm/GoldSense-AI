from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = Path("data/kjpl/kjpl_rates.csv")
OUTPUT_PATH = Path("backend/ml/data/processed/kjpl_events.csv")

IST = "Asia/Kolkata"


def load_raw_data() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"KJPL data not found: {INPUT_PATH}"
        )

    df = pd.read_csv(INPUT_PATH)

    required_columns = {
        "observed_at",
        "published_time",
        "gold_mjdta",
        "silver_mjdta",
        "source",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    return df


def clean_events(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    # ---------------------------------------------------------
    # 1. Parse the time when our collector observed KJPL.
    # ---------------------------------------------------------
    result["observed_at"] = pd.to_datetime(
        result["observed_at"],
        utc=True,
        errors="coerce",
    )

    result = result.dropna(
        subset=["observed_at"]
    )

    # Convert observation timestamp to IST.
    result["observed_at_ist"] = (
        result["observed_at"]
        .dt.tz_convert(IST)
    )

    # ---------------------------------------------------------
    # 2. Extract KJPL's published clock time.
    #
    # Example:
    # "Time : 09:29 am" → "09:29 am"
    # ---------------------------------------------------------
    result["published_clock_text"] = (
        result["published_time"]
        .astype(str)
        .str.replace(
            "Time :",
            "",
            regex=False,
        )
        .str.strip()
    )

    result["published_clock"] = pd.to_datetime(
        result["published_clock_text"],
        format="%I:%M %p",
        errors="coerce",
    ).dt.time

    result = result.dropna(
        subset=["published_clock"]
    )

    # ---------------------------------------------------------
    # 3. Parse numeric rates.
    # ---------------------------------------------------------
    result["gold_mjdta"] = pd.to_numeric(
        result["gold_mjdta"],
        errors="coerce",
    )

    result["silver_mjdta"] = pd.to_numeric(
        result["silver_mjdta"],
        errors="coerce",
    )

    result = result.dropna(
        subset=["gold_mjdta"]
    )

    # ---------------------------------------------------------
    # 4. Construct the KJPL event timestamp.
    #
    # KJPL gives us the published CLOCK time.
    # Our scraper gives us the DATE.
    #
    # Example:
    # observed date = 2026-09-28
    # published     = 04:27 PM
    #
    # event_time    = 2026-09-28 16:27 IST
    # ---------------------------------------------------------
    result["event_date"] = (
        result["observed_at_ist"].dt.date
    )

    result["event_time"] = pd.to_datetime(
        result["event_date"].astype(str)
        + " "
        + result["published_clock_text"],
        format="%Y-%m-%d %I:%M %p",
        errors="coerce",
    )

    result["event_time"] = (
        result["event_time"]
        .dt.tz_localize(IST)
    )

    result = result.dropna(
        subset=["event_time"]
    )

    # ---------------------------------------------------------
    # 5. Sort chronologically.
    # ---------------------------------------------------------
    result = result.sort_values(
        "event_time"
    )

    # ---------------------------------------------------------
    # 6. Deduplicate repeated scraper observations.
    #
    # IMPORTANT:
    # event_time includes the DATE.
    #
    # Therefore:
    #
    # Sep 19 09:29 ₹14,285
    # Sep 20 09:29 ₹14,285
    #
    # remain two separate events.
    #
    # But:
    #
    # Sep 19 09:29 ₹14,285
    # Sep 19 09:29 ₹14,285
    #
    # becomes one event.
    # ---------------------------------------------------------
    result = result.drop_duplicates(
        subset=[
            "event_time",
            "gold_mjdta",
            "silver_mjdta",
        ],
        keep="first",
    )

    result = result.sort_values(
        "event_time"
    ).reset_index(drop=True)

    # ---------------------------------------------------------
    # 7. Stable event ID.
    # ---------------------------------------------------------
    result["event_id"] = (
        result.index + 1
    )

    # ---------------------------------------------------------
    # 8. Weekend / calendar features.
    # ---------------------------------------------------------
    result["day_of_week"] = (
        result["event_time"].dt.day_name()
    )

    result["day_of_week_num"] = (
        result["event_time"].dt.dayofweek
    )

    result["is_weekend"] = (
        result["day_of_week_num"] >= 5
    )

    # ---------------------------------------------------------
    # 9. Keep useful event-level columns.
    # ---------------------------------------------------------
    result = result[
        [
            "event_id",
            "event_time",
            "observed_at",
            "observed_at_ist",
            "published_time",
            "gold_mjdta",
            "silver_mjdta",
            "day_of_week",
            "day_of_week_num",
            "is_weekend",
            "source",
        ]
    ]

    return result


def add_event_targets(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = df.copy()

    result = result.sort_values(
        "event_time"
    ).reset_index(drop=True)

    # ---------------------------------------------------------
    # Next actual KJPL event.
    # ---------------------------------------------------------
    result["next_event_time"] = (
        result["event_time"].shift(-1)
    )

    result["next_event_gold"] = (
        result["gold_mjdta"].shift(-1)
    )

    # ---------------------------------------------------------
    # Price change.
    # ---------------------------------------------------------
    result["target_change"] = (
        result["next_event_gold"]
        - result["gold_mjdta"]
    )

    result["target_change_pct"] = (
        result["target_change"]
        / result["gold_mjdta"]
        * 100
    )

    # ---------------------------------------------------------
    # Direction.
    # ---------------------------------------------------------
    result["target_direction"] = "FLAT"

    result.loc[
        result["target_change"] > 0,
        "target_direction",
    ] = "UP"

    result.loc[
        result["target_change"] < 0,
        "target_direction",
    ] = "DOWN"

    # ---------------------------------------------------------
    # The final event has no future event yet.
    #
    # Therefore its target is unknown, NOT FLAT.
    # ---------------------------------------------------------
    last_event = (
        result["next_event_time"].isna()
    )

    result.loc[
        last_event,
        [
            "next_event_gold",
            "target_change",
            "target_change_pct",
        ],
    ] = pd.NA

    result.loc[
        last_event,
        "target_direction",
    ] = pd.NA

    return result


def main() -> None:
    print(
        "[KJPL] Loading raw observations..."
    )

    raw = load_raw_data()

    print(
        f"[KJPL] Raw observations: {len(raw)}"
    )

    events = clean_events(raw)

    print(
        f"[KJPL] Unique KJPL events: {len(events)}"
    )

    events = add_event_targets(events)

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    events.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        f"[KJPL] Saved cleaned events to "
        f"{OUTPUT_PATH}"
    )

    print(
        "\n[KJPL] Events:"
    )

    print(
        events[
            [
                "event_id",
                "event_time",
                "gold_mjdta",
                "silver_mjdta",
                "day_of_week",
                "is_weekend",
                "target_direction",
            ]
        ].to_string(index=False)
    )

    print(
        "\n[KJPL] Target distribution:"
    )

    print(
        events[
            "target_direction"
        ].value_counts(dropna=False).to_string()
    )


if __name__ == "__main__":
    main()