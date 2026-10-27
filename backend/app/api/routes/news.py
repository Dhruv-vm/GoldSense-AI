from __future__ import annotations

import csv
from pathlib import Path
from fastapi import APIRouter

from app.services.data_service import PROJECT_ROOT, NEWS_CSV, ANALYZED_NEWS_CSV
from app.services.sentiment.relevance import GoldRelevanceScorer

router = APIRouter(prefix="/api/news", tags=["News"])
scorer = GoldRelevanceScorer()


@router.get("/latest")
def get_latest_news(limit: int = 30):
    """
    Returns latest financial and bullion news with gold relevance and sentiment indicators.
    """
    articles = []

    # Prefer analyzed news if present
    if ANALYZED_NEWS_CSV.exists():
        with ANALYZED_NEWS_CSV.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            for r in reader[-limit:]:
                articles.append({
                    "title": r["title"],
                    "url": r["url"],
                    "source": r["source"],
                    "published_at": r["published_at"],
                    "sentiment_label": r.get("sentiment_label", "neutral"),
                    "sentiment_score": float(r.get("sentiment_score", 0.0)),
                    "is_gold_relevant": r.get("is_gold_relevant", "True") == "True",
                    "primary_category": r.get("primary_category", "GOLD_DIRECT"),
                })
        articles.reverse()
        return articles

    # Fallback to raw news
    if NEWS_CSV.exists():
        with NEWS_CSV.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            for r in reader[-limit:]:
                rel = scorer.score_text(r["title"])
                articles.append({
                    "title": r["title"],
                    "url": r["url"],
                    "source": r["source"],
                    "published_at": r["published_at"],
                    "sentiment_label": "neutral",
                    "sentiment_score": 0.0,
                    "is_gold_relevant": rel.is_gold_relevant,
                    "primary_category": rel.primary_category,
                })
        articles.reverse()
        return articles

    return []


@router.get("/summary")
def get_news_summary():
    """
    Aggregated news intelligence metrics.
    """
    articles = get_latest_news(limit=50)
    total = len(articles)
    if total == 0:
        return {"total": 0, "positive_ratio": 0.0, "negative_ratio": 0.0, "neutral_ratio": 0.0}

    pos = sum(1 for a in articles if a["sentiment_label"] == "positive")
    neg = sum(1 for a in articles if a["sentiment_label"] == "negative")
    neu = sum(1 for a in articles if a["sentiment_label"] == "neutral")
    gold_rel = sum(1 for a in articles if a["is_gold_relevant"])

    return {
        "total_analyzed": total,
        "positive_ratio": round(pos / total, 2),
        "negative_ratio": round(neg / total, 2),
        "neutral_ratio": round(neu / total, 2),
        "gold_relevant_count": gold_rel,
        "gold_relevant_ratio": round(gold_rel / total, 2),
    }
