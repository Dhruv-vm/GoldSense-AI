from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Query

from app.services.data_service import PROJECT_ROOT, NEWS_CSV, LIVE_NEWS_CSV, NEWS_ARCHIVE_CSV, ANALYZED_NEWS_CSV
from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.live_signal import get_live_news_intelligence, parse_utc_timestamp
from app.services.sentiment.relevance import GoldRelevanceScorer

router = APIRouter(prefix="/api/news", tags=["News"])
scorer = GoldRelevanceScorer()


@router.get("/latest")
def get_latest_news(
    limit: int = 30,
    window_hours: int | None = None,
):
    """
    Returns latest financial and bullion news with gold relevance, sentiment indicators,
    and bullion directional impact.
    Prioritizes the dedicated LIVE_NEWS_CSV dataset.
    """
    articles = []
    now = datetime.now(timezone.utc)
    if not isinstance(limit, int):
        try:
            limit = int(limit)
        except Exception:
            limit = 30
    if window_hours is not None and not isinstance(window_hours, (int, float)):
        try:
            window_hours = float(window_hours)
        except Exception:
            window_hours = None

    # Priority 1: Dedicated fresh LIVE_NEWS_CSV
    if LIVE_NEWS_CSV.exists():
        try:
            with LIVE_NEWS_CSV.open("r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
                for r in reader:
                    pub_dt = parse_utc_timestamp(r.get("published_at", ""))
                    if window_hours is not None and pub_dt:
                        age_h = (now - pub_dt).total_seconds() / 3600.0
                        if age_h > window_hours:
                            continue

                    articles.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                        "published_at": r.get("published_at", ""),
                        "sentiment_label": r.get("directional_implication", "neutral").lower(),
                        "sentiment_score": 0.0,
                        "is_gold_relevant": r.get("is_gold_relevant", "True").lower() in ("true", "1"),
                        "primary_category": r.get("primary_category", "GOLD_DIRECT"),
                        "driver_category": r.get("driver_category", "MARKET_MOMENTUM"),
                        "directional_implication": r.get("directional_implication", "UNCERTAIN"),
                        "confidence": r.get("confidence", "MEDIUM"),
                        "evidence_rationale": r.get("evidence_rationale", ""),
                        "age_display": f"{round((now - pub_dt).total_seconds() / 3600.0, 1)}h ago" if pub_dt else "recent",
                        "syndicated_copies_count": int(r.get("syndicated_copies_count", 1) or 1),
                    })

                    if len(articles) >= limit:
                        break
            return articles
        except Exception:
            articles = []

    # Priority 2: Analyzed news cache
    if ANALYZED_NEWS_CSV.exists():
        with ANALYZED_NEWS_CSV.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            for r in reversed(reader):
                pub_dt = parse_utc_timestamp(r.get("published_at", ""))
                if window_hours is not None and pub_dt:
                    age_h = (now - pub_dt).total_seconds() / 3600.0
                    if age_h > window_hours:
                        continue

                title = r.get("title", "")
                sentiment_label = r.get("sentiment_label", "neutral")
                sentiment_score = float(r.get("sentiment_score", 0.0) or 0.0)
                is_gold_relevant = r.get("is_gold_relevant", "True") == "True"

                impact = evaluate_gold_impact(
                    title=title,
                    published_at=pub_dt or now,
                    finbert_label=sentiment_label,
                    finbert_score=sentiment_score,
                    reference_time=now,
                )

                articles.append({
                    "title": title,
                    "url": r.get("url", ""),
                    "source": r.get("source", ""),
                    "published_at": r.get("published_at", ""),
                    "sentiment_label": sentiment_label,
                    "sentiment_score": sentiment_score,
                    "is_gold_relevant": is_gold_relevant,
                    "primary_category": r.get("primary_category", "GOLD_DIRECT"),
                    "driver_category": impact["driver_category"],
                    "directional_implication": impact["directional_implication"],
                    "confidence": impact["confidence"],
                    "evidence_rationale": impact["evidence_rationale"],
                    "age_display": impact["age_display"],
                })

                if len(articles) >= limit:
                    break
        return articles

    # Fallback to raw news
    if NEWS_CSV.exists():
        with NEWS_CSV.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            for r in reversed(reader):
                pub_dt = parse_utc_timestamp(r.get("published_at", ""))
                if window_hours is not None and pub_dt:
                    age_h = (now - pub_dt).total_seconds() / 3600.0
                    if age_h > window_hours:
                        continue

                title = r.get("title", "")
                rel = scorer.score_text(title)
                impact = evaluate_gold_impact(
                    title=title,
                    published_at=pub_dt or now,
                    finbert_label="neutral",
                    finbert_score=0.0,
                    reference_time=now,
                )

                articles.append({
                    "title": title,
                    "url": r.get("url", ""),
                    "source": r.get("source", ""),
                    "published_at": r.get("published_at", ""),
                    "sentiment_label": "neutral",
                    "sentiment_score": 0.0,
                    "is_gold_relevant": rel.is_gold_relevant,
                    "primary_category": rel.primary_category.value if hasattr(rel.primary_category, "value") else str(rel.primary_category),
                    "driver_category": impact["driver_category"],
                    "directional_implication": impact["directional_implication"],
                    "confidence": impact["confidence"],
                    "evidence_rationale": impact["evidence_rationale"],
                    "age_display": impact["age_display"],
                })

                if len(articles) >= limit:
                    break
        return articles

    return []


@router.get("/live-signal")
def get_live_news_signal(
    window_hours: int = 24,
):
    """
    Returns real-time bullion news signal intelligence prioritized by freshness.
    Includes syndicated cluster deduplication, macro driver attribution, directional consensus,
    and market vs. news alignment.
    """
    if not isinstance(window_hours, int):
        try:
            window_hours = int(window_hours)
        except Exception:
            window_hours = 24
    return get_live_news_intelligence(window_hours=window_hours)


@router.get("/archive")
def get_news_archive(
    limit: int = 50,
    offset: int = 0,
    is_gold_relevant: bool | None = None,
):
    """
    Returns historical news articles from the research archive (isolated from live signal).
    Useful for ML researchers and point-in-time backtesting verification.
    """
    if not NEWS_ARCHIVE_CSV.exists():
        return {"total": 0, "articles": []}

    results = []
    with NEWS_ARCHIVE_CSV.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        total_records = len(reader)
        # Reverse to show newest historical entries first
        reversed_records = list(reversed(reader))

        for r in reversed_records[offset: offset + limit * 2]:
            rel = scorer.score_text(r.get("title", ""))
            if is_gold_relevant is not None and rel.is_gold_relevant != is_gold_relevant:
                continue

            results.append({
                "published_at": r.get("published_at", ""),
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "source": r.get("source", ""),
                "is_gold_relevant": rel.is_gold_relevant,
                "primary_category": rel.primary_category.value if hasattr(rel.primary_category, "value") else str(rel.primary_category),
            })
            if len(results) >= limit:
                break

    return {
        "total_archive_records": total_records,
        "returned": len(results),
        "offset": offset,
        "limit": limit,
        "articles": results,
    }


@router.get("/summary")
def get_news_summary():
    """
    Aggregated news intelligence metrics.
    """
    articles = get_latest_news(limit=50)
    total = len(articles)
    if total == 0:
        return {"total": 0, "positive_ratio": 0.0, "negative_ratio": 0.0, "neutral_ratio": 0.0}

    pos = sum(1 for a in articles if a["sentiment_label"] in ("positive", "bullish"))
    neg = sum(1 for a in articles if a["sentiment_label"] in ("negative", "bearish"))
    neu = sum(1 for a in articles if a["sentiment_label"] in ("neutral", "uncertain", "mixed"))
    gold_rel = sum(1 for a in articles if a["is_gold_relevant"])

    return {
        "total_analyzed": total,
        "positive_ratio": round(pos / total, 2),
        "negative_ratio": round(neg / total, 2),
        "neutral_ratio": round(neu / total, 2),
        "gold_relevant_count": gold_rel,
        "gold_relevant_ratio": round(gold_rel / total, 2),
    }
