from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.services.sentiment.schemas import AggregatedSentiment, AnalyzedArticle

LOOKBACK_WINDOWS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


class SentimentAggregator:
    """
    Aggregates financial, macroeconomic, and geopolitical news sentiment across multiple lookback windows
    (15m, 1h, 4h, 1d) with strict no-lookahead enforcement.

    For any event at T, ONLY articles published at or before T (published_at <= T)
    are included. Articles published after T are strictly discarded.
    """

    def __init__(
        self,
        lookbacks: dict[str, timedelta] | None = None,
    ) -> None:
        self.lookbacks = lookbacks or LOOKBACK_WINDOWS

    def aggregate_for_timestamp(
        self,
        articles: list[AnalyzedArticle],
        cutoff_time: datetime | pd.Timestamp,
    ) -> AggregatedSentiment:
        """
        Aggregate sentiment features for a specific point in time (e.g. KJPL event_time).
        """
        if isinstance(cutoff_time, pd.Timestamp):
            if cutoff_time.tzinfo is None:
                cutoff_utc = cutoff_time.tz_localize("UTC").to_pydatetime()
            else:
                cutoff_utc = cutoff_time.tz_convert("UTC").to_pydatetime()
        elif isinstance(cutoff_time, datetime):
            if cutoff_time.tzinfo is None:
                cutoff_utc = cutoff_time.replace(tzinfo=timezone.utc)
            else:
                cutoff_utc = cutoff_time.astimezone(timezone.utc)
        else:
            raise ValueError(f"Unsupported timestamp type: {type(cutoff_time)}")

        # -------------------------------------------------------------
        # STRICT NO-LOOKAHEAD FILTER:
        # Keep ONLY articles published at or before the cutoff timestamp
        # -------------------------------------------------------------
        historical = [
            a for a in articles
            if self._ensure_utc(a.published_at) <= cutoff_utc
        ]

        # Time window means and counts
        window_means: dict[str, float | None] = {}
        window_counts: dict[str, int] = {}

        for name, delta in self.lookbacks.items():
            start_window = cutoff_utc - delta
            in_window = [
                a for a in historical
                if self._ensure_utc(a.published_at) >= start_window
            ]
            count = len(in_window)
            window_counts[name] = count

            if count > 0:
                mean_val = sum(a.sentiment_score for a in in_window) / count
                window_means[name] = round(mean_val, 4)
            else:
                # Missing history must remain missing (None / NaN), NOT 0.0
                window_means[name] = None

        # 1-day lookback for ratio features, gold-relevance, and category features
        start_1d = cutoff_utc - timedelta(days=1)
        in_1d = [
            a for a in historical
            if self._ensure_utc(a.published_at) >= start_1d
        ]
        n_1d = len(in_1d)

        pos_ratio: float | None = None
        neg_ratio: float | None = None
        neu_ratio: float | None = None
        gold_count = 0
        gold_mean_1d: float | None = None
        gold_ratio: float | None = None

        # Category level accumulators
        fed_arts = []
        geo_arts = []
        india_arts = []
        rbi_arts = []
        usd_arts = []
        treasury_arts = []
        oil_arts = []
        china_arts = []
        cb_gold_arts = []
        fin_risk_arts = []

        if n_1d > 0:
            pos_count = sum(1 for a in in_1d if a.sentiment_label == "positive")
            neg_count = sum(1 for a in in_1d if a.sentiment_label == "negative")
            neu_count = sum(1 for a in in_1d if a.sentiment_label == "neutral")

            pos_ratio = round(pos_count / n_1d, 4)
            neg_ratio = round(neg_count / n_1d, 4)
            neu_ratio = round(neu_count / n_1d, 4)

            gold_articles_1d = [a for a in in_1d if a.is_gold_relevant]
            gold_count = len(gold_articles_1d)
            gold_ratio = round(gold_count / n_1d, 4)

            if gold_count > 0:
                gold_mean_1d = round(
                    sum(a.sentiment_score for a in gold_articles_1d) / gold_count,
                    4,
                )

            # Category filtering
            for a in in_1d:
                cat = a.primary_category
                supp = set(a.supporting_categories)

                # Fed
                if cat == "US_FED_MONETARY_POLICY" or "US_FED_MONETARY_POLICY" in supp or a.us_relevance >= 0.5:
                    fed_arts.append(a)

                # Geopolitics
                if (
                    cat in ("GEOPOLITICS", "TRADE_TARIFFS", "SANCTIONS")
                    or supp & {"GEOPOLITICS", "TRADE_TARIFFS", "SANCTIONS"}
                    or a.geopolitical_relevance >= 0.4
                ):
                    geo_arts.append(a)

                # India
                if (
                    cat.startswith("INDIA_")
                    or any(c.startswith("INDIA_") for c in supp)
                    or a.india_relevance >= 0.4
                ):
                    india_arts.append(a)

                # RBI
                if cat == "INDIA_RBI" or "INDIA_RBI" in supp:
                    rbi_arts.append(a)

                # USD
                if cat in ("US_DOLLAR", "GLOBAL_FX") or supp & {"US_DOLLAR", "GLOBAL_FX"}:
                    usd_arts.append(a)

                # Treasury
                if cat == "US_TREASURY_YIELDS" or "US_TREASURY_YIELDS" in supp:
                    treasury_arts.append(a)

                # Oil
                if cat == "OIL_ENERGY" or "OIL_ENERGY" in supp:
                    oil_arts.append(a)

                # China
                if cat in ("CHINA_GOLD", "CHINA_MACRO") or supp & {"CHINA_GOLD", "CHINA_MACRO"}:
                    china_arts.append(a)

                # Central Bank Gold
                if cat == "CENTRAL_BANK_GOLD" or "CENTRAL_BANK_GOLD" in supp:
                    cb_gold_arts.append(a)

                # Financial Risk
                if cat == "GLOBAL_FINANCIAL_RISK" or "GLOBAL_FINANCIAL_RISK" in supp:
                    fin_risk_arts.append(a)

        def _mean_score(arts: list[AnalyzedArticle]) -> float | None:
            if not arts:
                return None
            return round(sum(a.sentiment_score for a in arts) / len(arts), 4)

        return AggregatedSentiment(
            sentiment_mean_15m=window_means.get("15m"),
            sentiment_mean_1h=window_means.get("1h"),
            sentiment_mean_4h=window_means.get("4h"),
            sentiment_mean_1d=window_means.get("1d"),
            news_count_15m=window_counts.get("15m", 0),
            news_count_1h=window_counts.get("1h", 0),
            news_count_4h=window_counts.get("4h", 0),
            news_count_1d=window_counts.get("1d", 0),
            negative_news_ratio=neg_ratio,
            positive_news_ratio=pos_ratio,
            neutral_news_ratio=neu_ratio,
            gold_relevant_news_count=gold_count,
            gold_sentiment_mean_1d=gold_mean_1d,
            gold_relevant_ratio=gold_ratio,
            # Category-level features
            fed_article_count=len(fed_arts),
            fed_sentiment_mean=_mean_score(fed_arts),
            geopolitical_article_count=len(geo_arts),
            geopolitical_sentiment_mean=_mean_score(geo_arts),
            india_article_count=len(india_arts),
            india_sentiment_mean=_mean_score(india_arts),
            rbi_article_count=len(rbi_arts),
            usd_article_count=len(usd_arts),
            usd_sentiment_mean=_mean_score(usd_arts),
            treasury_article_count=len(treasury_arts),
            oil_article_count=len(oil_arts),
            china_article_count=len(china_arts),
            central_bank_gold_article_count=len(cb_gold_arts),
            financial_risk_article_count=len(fin_risk_arts),
        )

    def aggregate_for_events(
        self,
        events_df: pd.DataFrame,
        analyzed_articles: list[AnalyzedArticle],
        time_col: str = "event_time",
    ) -> pd.DataFrame:
        """
        Calculates sentiment features for each row in events_df based on its event timestamp.
        Returns a DataFrame containing the aligned sentiment feature columns.
        """
        if events_df.empty:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        for _, row in events_df.iterrows():
            cutoff = row[time_col]
            agg = self.aggregate_for_timestamp(analyzed_articles, cutoff)
            rows.append(agg.model_dump())

        return pd.DataFrame(rows, index=events_df.index)

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
