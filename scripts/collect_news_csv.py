from __future__ import annotations

import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.sentiment.news_client import NewsClient

OUTPUT = Path("data/news/news_articles.csv")


def collect() -> None:
    lookback_hours = int(os.environ.get("NEWS_LOOKBACK_HOURS", "6"))
    print(f"[NEWS CSV] Starting news collection across query groups (lookback={lookback_hours}h)...")

    client = NewsClient()
    articles = client.search_query_groups(
        lookback_hours=lookback_hours,
        max_records_per_group=15,
    )

    if not articles:
        print("[NEWS CSV] No new articles found or sources unavailable.")
        return

    new_saved = NewsClient.save_to_csv(articles, OUTPUT)
    print(f"[NEWS CSV] Processed {len(articles)} articles. Added {new_saved} new unique articles to {OUTPUT}")


if __name__ == "__main__":
    collect()
