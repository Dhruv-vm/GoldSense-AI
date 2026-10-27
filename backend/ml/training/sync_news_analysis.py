from __future__ import annotations

import csv
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.sentiment.relevance import GoldRelevanceScorer

RAW_NEWS_PATH = PROJECT_ROOT / "data/news/news_articles.csv"
ANALYZED_NEWS_PATH = PROJECT_ROOT / "backend/ml/data/processed/analyzed_news.csv"


def sync_analyzed_news(max_batch: int = 500) -> int:
    """
    Incrementally process unanalyzed raw news articles and append to analyzed_news.csv cache.
    """
    if not RAW_NEWS_PATH.exists():
        print(f"[NEWS SYNC] Raw news not found at {RAW_NEWS_PATH}")
        return 0

    df_raw = pd.read_csv(RAW_NEWS_PATH)
    ANALYZED_NEWS_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing_urls = set()
    if ANALYZED_NEWS_PATH.exists():
        df_existing = pd.read_csv(ANALYZED_NEWS_PATH)
        existing_urls = set(df_existing["url"].dropna().unique())
        print(f"[NEWS SYNC] Existing analyzed cache contains {len(df_existing)} articles.")
    else:
        df_existing = pd.DataFrame()

    unprocessed = df_raw[~df_raw["url"].isin(existing_urls)].copy()
    if unprocessed.empty:
        print("[NEWS SYNC] All raw articles are already analyzed.")
        return 0

    print(f"[NEWS SYNC] Found {len(unprocessed)} unanalyzed articles. Processing up to {max_batch}...")
    batch = unprocessed.head(max_batch).copy()

    scorer = GoldRelevanceScorer()
    new_rows = []

    for _, row in batch.iterrows():
        title = str(row["title"])
        rel = scorer.score_text(title)

        # Fast rule-based financial sentiment for batch sync
        # Negative cues
        lower_t = title.lower()
        neg_cues = ["falls", "drops", "slips", "slides", "tumbles", "slashes", "retreats", "declines", "cheaper", "plunges", "down", "low"]
        pos_cues = ["rallies", "surges", "climbs", "rebounds", "gains", "record high", "jumps", "boosts", "steady", "up"]

        has_neg = any(c in lower_t for c in neg_cues)
        has_pos = any(c in lower_t for c in pos_cues)

        if has_neg and not has_pos:
            sent_label = "negative"
            sent_score = -0.75
            pos_p, neg_p, neu_p = 0.1, 0.8, 0.1
        elif has_pos and not has_neg:
            sent_label = "positive"
            sent_score = +0.65
            pos_p, neg_p, neu_p = 0.7, 0.1, 0.2
        else:
            sent_label = "neutral"
            sent_score = 0.0
            pos_p, neg_p, neu_p = 0.1, 0.1, 0.8

        new_rows.append({
            "published_at": row["published_at"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "language": row.get("language", "en"),
            "positive_probability": pos_p,
            "negative_probability": neg_p,
            "neutral_probability": neu_p,
            "sentiment_score": sent_score,
            "sentiment_label": sent_label,
            "is_gold_relevant": rel.is_gold_relevant,
            "gold_relevance_score": rel.gold_relevance_score,
            "primary_category": rel.primary_category,
            "supporting_categories": rel.supporting_categories,
            "geopolitical_relevance": rel.geopolitical_relevance,
            "india_relevance": rel.india_relevance,
            "us_relevance": rel.us_relevance,
            "macro_relevance": rel.macro_relevance,
            "market_relevance": rel.market_relevance,
        })

    df_new = pd.DataFrame(new_rows)
    if df_existing.empty:
        df_combined = df_new
    else:
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)

    df_combined.to_csv(ANALYZED_NEWS_PATH, index=False)
    print(f"[NEWS SYNC] Appended {len(df_new)} new analyzed rows. Total cache size: {len(df_combined)}")
    return len(df_new)


if __name__ == "__main__":
    sync_analyzed_news()
