from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.feature_snapshot import FeatureSnapshot
from app.models.gold_rate import GoldRate


# 1 troy ounce = 31.1034768 grams
TROY_OUNCE_TO_GRAMS = 31.1034768


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0

    return ((current - previous) / previous) * 100.0


def _gold_usd_to_inr_per_gram(
    xauusd: float,
    usdinr: float,
) -> float:
    """
    Convert international gold price from
    USD per troy ounce to INR per gram.
    """
    return (xauusd * usdinr) / TROY_OUNCE_TO_GRAMS


def build_training_dataset():
    """
    Build an event-aware KJPL training dataset.

    A training sample represents:

        current KJPL publication event
                    ↓
        market conditions before the event
                    ↓
        next KJPL publication event
                    ↓
        actual price change

    Hourly feature snapshots are used for market features,
    but unchanged hourly KJPL observations are NOT treated
    as separate prediction targets.
    """

    db = SessionLocal()

    try:
        # --------------------------------------------------
        # Load feature snapshots
        # --------------------------------------------------

        snapshot_result = db.execute(
            select(FeatureSnapshot).order_by(
                FeatureSnapshot.observed_at.asc()
            )
        )

        snapshots = snapshot_result.scalars().all()

        # --------------------------------------------------
        # Load only KJPL rows with reliable publication dates
        # --------------------------------------------------

        event_result = db.execute(
            select(GoldRate)
            .where(
                GoldRate.source_updated_at.is_not(None)
            )
            .order_by(
                GoldRate.source_updated_at.asc()
            )
        )

        events = event_result.scalars().all()

        # We need at least two publication events
        # to calculate an event-to-event target.
        if len(events) < 2:
            return []

        dataset = []

        # --------------------------------------------------
        # Process each KJPL event
        # --------------------------------------------------

        for index, current_event in enumerate(events[:-1]):

            next_event = events[index + 1]

            # ----------------------------------------------
            # Find the latest feature snapshot at or before
            # the current KJPL publication event.
            # ----------------------------------------------

            eligible_snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.observed_at <= current_event.source_updated_at
            ]

            if not eligible_snapshots:
                continue

            current = eligible_snapshots[-1]

            # ----------------------------------------------
            # Find the previous feature snapshot
            # for return calculations.
            # ----------------------------------------------

            previous_candidates = [
                snapshot
                for snapshot in snapshots
                if snapshot.observed_at < current.observed_at
            ]

            if not previous_candidates:
                continue

            previous = previous_candidates[-1]

            # ----------------------------------------------
            # Target direction
            # ----------------------------------------------

            if next_event.gold_mjdta > current_event.gold_mjdta:
                direction = "UP"

            elif next_event.gold_mjdta < current_event.gold_mjdta:
                direction = "DOWN"

            else:
                direction = "FLAT"

            # ----------------------------------------------
            # Market return features
            # ----------------------------------------------

            gold_return = _pct_change(
                current.kjpl_gold,
                previous.kjpl_gold,
            )

            xau_return = _pct_change(
                current.xauusd,
                previous.xauusd,
            )

            xagusd_return = _pct_change(
                current.xagusd,
                previous.xagusd,
            )

            usdinr_return = _pct_change(
                current.usdinr,
                previous.usdinr,
            )

            # ----------------------------------------------
            # International gold → INR/gram
            # ----------------------------------------------

            gold_xau_inr_estimate = (
                _gold_usd_to_inr_per_gram(
                    current.xauusd,
                    current.usdinr,
                )
            )

            # ----------------------------------------------
            # KJPL premium vs global gold estimate
            # ----------------------------------------------

            if gold_xau_inr_estimate != 0:
                kjpl_global_premium_pct = (
                    (
                        (
                            current.kjpl_gold
                            - gold_xau_inr_estimate
                        )
                        / gold_xau_inr_estimate
                    )
                    * 100.0
                )
            else:
                kjpl_global_premium_pct = 0.0

            # ----------------------------------------------
            # Build training row
            # ----------------------------------------------

            dataset.append(
                {
                    "observed_at": current.observed_at,

                    # Current market state
                    "kjpl_gold": current.kjpl_gold,
                    "usdinr": current.usdinr,
                    "xauusd": current.xauusd,
                    "xagusd": current.xagusd,

                    # Return features
                    "gold_return_1h": gold_return,
                    "xau_return_1h": xau_return,
                    "xagusd_return_1h": xagusd_return,
                    "usdinr_return_1h": usdinr_return,

                    # Derived features
                    "gold_xau_ratio": (
                        current.kjpl_gold / current.xauusd
                        if current.xauusd != 0
                        else 0.0
                    ),

                    "gold_xau_inr_estimate": (
                        gold_xau_inr_estimate
                    ),

                    "kjpl_global_premium_pct": (
                        kjpl_global_premium_pct
                    ),

                    # Event-aware target
                    "target_time": next_event.source_updated_at,
                    "target_gold": next_event.gold_mjdta,
                    "target_direction": direction,
                }
            )

        return dataset

    finally:
        db.close()