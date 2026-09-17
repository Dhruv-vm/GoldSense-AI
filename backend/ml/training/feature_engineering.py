from __future__ import annotations

from datetime import timedelta

import pandas as pd


LOOKBACKS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def pct_change(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None

    return ((current - previous) / previous) * 100


def get_previous_value(
    df: pd.DataFrame,
    timestamp: pd.Timestamp,
    column: str,
    lookback: timedelta,
) -> float | None:
    cutoff = timestamp - lookback

    candidates = df[
        (df["observed_at"] <= cutoff)
        & df[column].notna()
    ]

    if candidates.empty:
        return None

    return float(candidates.iloc[-1][column])


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add timestamp-aware market features.

    Features are calculated using actual timestamps rather than
    assuming that consecutive database rows represent equal time intervals.
    """

    if df.empty:
        return df.copy()

    result = df.copy()

    result["observed_at"] = pd.to_datetime(
        result["observed_at"],
        utc=True,
    )

    result = result.sort_values("observed_at").reset_index(drop=True)

    for label, lookback in LOOKBACKS.items():
        result[f"gold_return_{label}"] = None
        result[f"xau_return_{label}"] = None
        result[f"xagusd_return_{label}"] = None
        result[f"usdinr_return_{label}"] = None

        for i, row in result.iterrows():
            timestamp = row["observed_at"]

            previous_gold = get_previous_value(
                result,
                timestamp,
                "kjpl_gold",
                lookback,
            )

            previous_xau = get_previous_value(
                result,
                timestamp,
                "xauusd",
                lookback,
            )

            previous_xagusd = get_previous_value(
                result,
                timestamp,
                "xagusd",
                lookback,
            )

            previous_usdinr = get_previous_value(
                result,
                timestamp,
                "usdinr",
                lookback,
            )

            result.at[i, f"gold_return_{label}"] = pct_change(
                row["kjpl_gold"],
                previous_gold,
            )

            result.at[i, f"xau_return_{label}"] = pct_change(
                row["xauusd"],
                previous_xau,
            )

            result.at[i, f"xagusd_return_{label}"] = pct_change(
                row["xagusd"],
                previous_xagusd,
            )

            result.at[i, f"usdinr_return_{label}"] = pct_change(
                row["usdinr"],
                previous_usdinr,
            )

    # Approximate international gold value in INR/gram.
    # Troy ounce -> gram conversion.
    TROY_OUNCE_GRAMS = 31.1034768

    result["gold_xau_inr_estimate"] = (
        result["xauusd"]
        * result["usdinr"]
        / TROY_OUNCE_GRAMS
    )

    # Difference between KJPL published gold and international
    # gold converted into INR/gram.
    result["kjpl_global_premium_pct"] = (
        (
            result["kjpl_gold"]
            - result["gold_xau_inr_estimate"]
        )
        / result["gold_xau_inr_estimate"]
    ) * 100

    # Basic market relationships.
    result["gold_xau_ratio"] = (
        result["kjpl_gold"]
        / result["gold_xau_inr_estimate"]
    )

    return result