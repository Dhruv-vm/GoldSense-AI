from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = Path("data/market/market_rates.csv")
OUTPUT_PATH = Path("backend/ml/data/processed/market_features.csv")

LOOKBACKS = {
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}

TROY_OUNCE_GRAMS = 31.1034768


def load_market_data() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Market data not found: {INPUT_PATH}"
        )

    df = pd.read_csv(INPUT_PATH)

    required = {
        "observed_at",
        "usdinr",
        "xauusd",
        "xagusd",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    df["observed_at"] = pd.to_datetime(
        df["observed_at"],
        utc=True,
        errors="coerce",
    )

    numeric_columns = [
        "usdinr",
        "xauusd",
        "xagusd",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df.dropna(
        subset=[
            "observed_at",
            *numeric_columns,
        ]
    )

    df = (
        df.sort_values("observed_at")
        .drop_duplicates(subset=["observed_at"], keep="last")
        .reset_index(drop=True)
    )

    return df


def get_previous_value(
    df: pd.DataFrame,
    timestamp: pd.Timestamp,
    column: str,
    lookback: pd.Timedelta,
) -> float | None:
    """
    Find a previous observation near the requested lookback.

    We allow a limited tolerance because the collector does
    not run at perfectly regular intervals.

    If the nearest valid observation is too old, return None.
    """

    target_time = timestamp - lookback

    # Maximum acceptable distance from the desired lookback.
    tolerance = {
        pd.Timedelta(minutes=15): pd.Timedelta(minutes=20),
        pd.Timedelta(hours=1): pd.Timedelta(minutes=45),
        pd.Timedelta(hours=4): pd.Timedelta(hours=2),
        pd.Timedelta(days=1): pd.Timedelta(hours=6),
    }[lookback]

    previous = df.loc[
        df["observed_at"] <= target_time,
        ["observed_at", column],
    ]

    if previous.empty:
        return None

    previous_row = previous.iloc[-1]

    actual_time = previous_row["observed_at"]
    age = target_time - actual_time

    if age > tolerance:
        return None

    return float(previous_row[column])


def calculate_return(
    current: float,
    previous: float | None,
) -> float | None:

    if previous is None or previous == 0:
        return None

    return ((current - previous) / previous) * 100


def add_market_returns(df: pd.DataFrame) -> pd.DataFrame:

    result = df.copy()

    for lookback_name, lookback in LOOKBACKS.items():

        for column in ["usdinr", "xauusd", "xagusd"]:

            feature_name = (
                f"{column}_return_{lookback_name}"
            )

            values = []

            for _, row in result.iterrows():

                previous = get_previous_value(
                    result,
                    row["observed_at"],
                    column,
                    lookback,
                )

                current = float(row[column])

                values.append(
                    calculate_return(
                        current,
                        previous,
                    )
                )

            result[feature_name] = values

    return result


def add_market_derived_features(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = df.copy()

    # Convert international gold price:
    #
    # XAUUSD = USD per troy ounce
    # USDINR = INR per USD
    #
    # Therefore:
    #
    # INR per troy ounce =
    # XAUUSD * USDINR
    #
    # INR per gram =
    # INR per troy ounce / 31.1034768

    result["gold_global_inr_per_gram"] = (
        result["xauusd"]
        * result["usdinr"]
        / TROY_OUNCE_GRAMS
    )

    # Silver equivalent INR/gram.
    result["silver_global_inr_per_gram"] = (
        result["xagusd"]
        * result["usdinr"]
        / TROY_OUNCE_GRAMS
    )

    # Gold/Silver ratio.
    result["gold_silver_ratio"] = (
        result["xauusd"]
        / result["xagusd"]
    )

    return result


def add_time_features(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = df.copy()

    # Convert to IST for calendar/session features.
    ist_time = result["observed_at"].dt.tz_convert(
        "Asia/Kolkata"
    )

    result["hour"] = ist_time.dt.hour
    result["minute"] = ist_time.dt.minute

    result["day_of_week"] = ist_time.dt.dayofweek

    result["is_weekend"] = (
        result["day_of_week"] >= 5
    )

    result["is_monday"] = (
        result["day_of_week"] == 0
    )

    result["is_friday"] = (
        result["day_of_week"] == 4
    )

    return result


def add_market_staleness(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = df.copy()

    # Time since the previous market observation.
    result["observation_gap_minutes"] = (
        result["observed_at"]
        .diff()
        .dt.total_seconds()
        / 60
    )

    # Large gaps indicate that the latest market value
    # may be stale because the market/data feed was closed.
    result["market_stale"] = (
        result["observation_gap_minutes"] > 180
    )

    return result


def build_features(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = add_market_returns(df)

    result = add_market_derived_features(
        result
    )

    result = add_time_features(
        result
    )

    result = add_market_staleness(
        result
    )

    return result


def main() -> None:

    print("[MARKET] Loading raw market data...")

    df = load_market_data()

    print(
        f"[MARKET] Raw observations: {len(df)}"
    )

    features = build_features(df)

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    features.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print(
        f"[MARKET] Saved features to "
        f"{OUTPUT_PATH}"
    )

    print(
        "\n[MARKET] Feature columns:"
    )

    print(
        "\n".join(features.columns)
    )

    print(
        "\n[MARKET] Latest features:"
    )

    print(
        features.tail(5).to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()