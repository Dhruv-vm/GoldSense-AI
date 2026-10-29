from __future__ import annotations

import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.sentiment.news_client import NewsClient

ARCHIVE_OUTPUT = Path("data/news/news_articles.csv")
LIVE_OUTPUT = Path("data/news/live_news.csv")


def collect() -> None:
    lookback_hours = int(os.environ.get("NEWS_LOOKBACK_HOURS", "24"))
    max_retention_hours = int(os.environ.get("NEWS_LIVE_RETENTION_HOURS", "72"))
    print(
        f"[NEWS CSV] Starting freshness-first news collection "
        f"(lookback={lookback_hours}h, live_retention={max_retention_hours}h)..."
    )

    client = NewsClient()
    articles = client.search_query_groups(
        lookback_hours=lookback_hours,
        max_records_per_group=20,
    )

    if not articles:
        print("[NEWS CSV] Notice: No new articles returned from active sources in this batch.")

    stats = NewsClient.save_news_datasets(
        articles=articles,
        live_csv_path=LIVE_OUTPUT,
        archive_csv_path=ARCHIVE_OUTPUT,
        lookback_hours=lookback_hours,
        max_live_retention_hours=max_retention_hours,
    )

    print(
        f"[NEWS CSV] Collection complete: "
        f"Archived {stats['new_archive_count']} new items to research archive ({ARCHIVE_OUTPUT}). "
        f"Live dataset now contains {stats['live_count']} fresh relevant articles in {LIVE_OUTPUT} "
        f"(pruned {stats['pruned_count']} stale/future entries)."
    )


if __name__ == "__main__":
    collect()
