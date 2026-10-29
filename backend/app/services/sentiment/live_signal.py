from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.data_service import ANALYZED_NEWS_CSV, NEWS_CSV, LIVE_NEWS_CSV, get_market_overview
from app.services.sentiment.gold_impact import (
    GoldDriver,
    evaluate_gold_impact,
    extract_cluster_key,
)
from app.services.sentiment.relevance import GoldRelevanceScorer

scorer = GoldRelevanceScorer()

CONFIDENCE_WEIGHTS = {
    "HIGH": 1.0,
    "MEDIUM": 0.65,
    "LOW": 0.35,
}


def parse_utc_timestamp(ts_str: str) -> datetime | None:
    """Parses an ISO or standard timestamp string into timezone-aware UTC datetime."""
    if not ts_str or not ts_str.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts_str.strip())
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # Fallback for common space-separated formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(ts_str.strip(), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def get_live_news_intelligence(
    window_hours: int = 24,
    reference_time: datetime | None = None,
    live_csv_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Computes real-time, freshness-prioritized bullion news intelligence.

    1. Enforces a strict recency window (default: last 24h).
    2. Filters for genuinely gold-relevant macroeconomic and commodity news.
    3. Clusters syndicated articles to prevent identical wire reprints from inflating signals.
    4. Evaluates domain-specific bullion directional impact grounded in macro transmission channels.
    5. Returns transparent status (e.g. INSUFFICIENT_FRESH_RELEVANT_NEWS if < 2 distinct clusters).
    6. Compares news directional consensus against real-time market movements.
    """
    now = reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    window_hours = max(1, int(window_hours))
    cutoff_time = now - timedelta(hours=window_hours)

    raw_candidates: list[dict[str, Any]] = []
    target_live_path = Path(live_csv_path) if live_csv_path else LIVE_NEWS_CSV

    # Priority 1: Read dedicated live news dataset
    if target_live_path.exists():
        try:
            with target_live_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    pub_dt = parse_utc_timestamp(r.get("published_at", ""))
                    if not pub_dt or pub_dt < cutoff_time or pub_dt > now + timedelta(minutes=15):
                        continue

                    is_gold_rel = r.get("is_gold_relevant", "False").lower() in ("true", "1")
                    raw_candidates.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                        "published_at": pub_dt,
                        "sentiment_label": r.get("sentiment_label", "neutral"),
                        "sentiment_score": float(r.get("sentiment_score", 0.0) or 0.0),
                        "is_gold_relevant": is_gold_rel,
                        "primary_category": r.get("primary_category", "GOLD_DIRECT"),
                        "driver_category": r.get("driver_category"),
                        "directional_implication": r.get("directional_implication"),
                        "confidence": r.get("confidence"),
                        "evidence_rationale": r.get("evidence_rationale"),
                        "cluster_key": r.get("cluster_key"),
                        "syndicated_copies_count": int(r.get("syndicated_copies_count", 1) or 1),
                    })
        except Exception:
            raw_candidates = []

    # Priority 2: Fallback to analyzed news or raw news (or for point-in-time historical evaluation)
    if not raw_candidates and ANALYZED_NEWS_CSV.exists():
        try:
            with ANALYZED_NEWS_CSV.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    pub_dt = parse_utc_timestamp(r.get("published_at", ""))
                    if not pub_dt or pub_dt < cutoff_time or pub_dt > now + timedelta(minutes=15):
                        continue

                    is_gold_rel = r.get("is_gold_relevant", "False").lower() in ("true", "1")
                    raw_candidates.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                        "published_at": pub_dt,
                        "sentiment_label": r.get("sentiment_label", "neutral"),
                        "sentiment_score": float(r.get("sentiment_score", 0.0) or 0.0),
                        "is_gold_relevant": is_gold_rel,
                        "primary_category": r.get("primary_category", "GOLD_DIRECT"),
                    })
        except Exception:
            raw_candidates = []

    # Fallback to raw news if analyzed news produced no fresh candidates
    if not raw_candidates and NEWS_CSV.exists():
        try:
            with NEWS_CSV.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    pub_dt = parse_utc_timestamp(r.get("published_at", ""))
                    if not pub_dt or pub_dt < cutoff_time or pub_dt > now + timedelta(minutes=15):
                        continue

                    rel = scorer.score_text(r.get("title", ""))
                    raw_candidates.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                        "published_at": pub_dt,
                        "sentiment_label": "neutral",
                        "sentiment_score": 0.0,
                        "is_gold_relevant": rel.is_gold_relevant,
                        "primary_category": rel.primary_category.value if hasattr(rel.primary_category, "value") else str(rel.primary_category),
                    })
        except Exception:
            pass

    total_fresh_scanned = len(raw_candidates)

    # Filter for gold relevance and evaluate directional impact
    relevant_evaluated: list[dict[str, Any]] = []
    for art in raw_candidates:
        impact = evaluate_gold_impact(
            title=art["title"],
            published_at=art["published_at"],
            finbert_label=art["sentiment_label"],
            finbert_score=art["sentiment_score"],
            reference_time=now,
        )

        # Consider relevant if marked relevant by scorer or if specific bullion driver/direction was matched
        is_relevant = (
            art["is_gold_relevant"]
            or impact["driver_category"] != GoldDriver.OTHER_MACRO
            or impact["directional_implication"] in ("BULLISH", "BEARISH")
        )
        if is_relevant:
            art_payload = {
                **impact,
                "url": art["url"],
                "source": art["source"],
            }
            relevant_evaluated.append(art_payload)

    # Cluster syndicated articles by cluster_key
    clusters: dict[str, list[dict[str, Any]]] = {}
    for art in relevant_evaluated:
        ckey = art["cluster_key"]
        if ckey not in clusters:
            clusters[ckey] = []
        clusters[ckey].append(art)

    # Pick representative article for each cluster (highest confidence, then highest freshness weight)
    cluster_representatives: list[dict[str, Any]] = []
    for ckey, cluster_items in clusters.items():
        # Sort cluster items so most prominent is first
        sorted_items = sorted(
            cluster_items,
            key=lambda x: (
                CONFIDENCE_WEIGHTS.get(x["confidence"], 0.5),
                x["freshness_weight"],
            ),
            reverse=True,
        )
        rep = dict(sorted_items[0])
        rep["syndicated_copies_count"] = len(cluster_items)
        cluster_representatives.append(rep)

    # Sort representatives by freshness weight * confidence descending
    cluster_representatives.sort(
        key=lambda x: x["freshness_weight"] * CONFIDENCE_WEIGHTS.get(x["confidence"], 0.5),
        reverse=True,
    )

    distinct_clusters_count = len(cluster_representatives)

    # Market movement alignment comparison
    market_overview = get_market_overview()
    market = market_overview.get("market", {})
    xauusd_change_pct = market.get("xauusd_change_24h_pct", 0.0) or 0.0

    # Insufficient fresh news guard (< 2 distinct relevant clusters)
    if distinct_clusters_count < 2:
        return {
            "status": "INSUFFICIENT_FRESH_RELEVANT_NEWS",
            "is_sufficient": False,
            "window_hours": window_hours,
            "evaluated_at": now.isoformat(),
            "total_fresh_scanned": total_fresh_scanned,
            "distinct_clusters_count": distinct_clusters_count,
            "relevant_fresh_count": len(relevant_evaluated),
            "message": (
                f"GoldSense AI detected {distinct_clusters_count} distinct fresh relevant news story cluster(s) "
                f"within the past {window_hours} hours ({total_fresh_scanned} total articles scanned). "
                f"At least 2 distinct clusters are required to establish an incremental directional news consensus "
                f"and avoid reporting false sentiment."
            ),
            "net_signal": "UNCERTAIN",
            "net_confidence": "LOW",
            "bullish_weight": 0.0,
            "bearish_weight": 0.0,
            "market_vs_news_alignment": "INSUFFICIENT_FRESH_NEWS",
            "driver_breakdown": {},
            "directional_breakdown": {"BULLISH": 0, "BEARISH": 0, "MIXED": 0, "UNCERTAIN": 0},
            "market_reference": {
                "xauusd": market.get("xauusd"),
                "xauusd_change_24h_pct": xauusd_change_pct,
                "usdinr": market.get("usdinr"),
            },
            "representative_articles": cluster_representatives,
        }

    # Aggregate directional weighted scores
    bullish_weight = 0.0
    bearish_weight = 0.0
    mixed_weight = 0.0
    driver_counts: dict[str, int] = {}
    directional_counts = {"BULLISH": 0, "BEARISH": 0, "MIXED": 0, "UNCERTAIN": 0}

    for rep in cluster_representatives:
        d = rep["directional_implication"]
        c = rep["confidence"]
        fw = rep["freshness_weight"]
        weight = fw * CONFIDENCE_WEIGHTS.get(c, 0.5)

        directional_counts[d] = directional_counts.get(d, 0) + 1
        driver_cat = rep["driver_category"]
        driver_counts[driver_cat] = driver_counts.get(driver_cat, 0) + 1

        if d == "BULLISH":
            bullish_weight += weight
        elif d == "BEARISH":
            bearish_weight += weight
        else:
            mixed_weight += weight

    bullish_weight = round(bullish_weight, 3)
    bearish_weight = round(bearish_weight, 3)
    mixed_weight = round(mixed_weight, 3)

    # Determine net directional consensus
    if bullish_weight >= 1.25 * bearish_weight and bullish_weight >= 0.4:
        net_signal = "BULLISH"
    elif bearish_weight >= 1.25 * bullish_weight and bearish_weight >= 0.4:
        net_signal = "BEARISH"
    elif abs(bullish_weight - bearish_weight) < 0.2 and (bullish_weight + bearish_weight) > 0.4:
        net_signal = "MIXED"
    else:
        net_signal = "NEUTRAL"

    # Determine net confidence
    total_effective = bullish_weight + bearish_weight + mixed_weight
    spread = abs(bullish_weight - bearish_weight)
    if distinct_clusters_count >= 5 and spread >= 0.8:
        net_confidence = "HIGH"
    elif distinct_clusters_count >= 3 and spread >= 0.4:
        net_confidence = "MEDIUM"
    else:
        net_confidence = "LOW"

    # Evaluate alignment between news consensus and market price action
    if net_signal == "BULLISH":
        if xauusd_change_pct >= 0.15:
            market_vs_news_alignment = "AGREES_BULLISH"
        elif xauusd_change_pct <= -0.15:
            market_vs_news_alignment = "DIVERGES_NEWS_BULLISH_MARKET_BEARISH"
        else:
            market_vs_news_alignment = "NEWS_BULLISH_MARKET_FLAT"
    elif net_signal == "BEARISH":
        if xauusd_change_pct <= -0.15:
            market_vs_news_alignment = "AGREES_BEARISH"
        elif xauusd_change_pct >= 0.15:
            market_vs_news_alignment = "DIVERGES_NEWS_BEARISH_MARKET_BULLISH"
        else:
            market_vs_news_alignment = "NEWS_BEARISH_MARKET_FLAT"
    elif net_signal == "MIXED":
        market_vs_news_alignment = "MIXED_SIGNALS_CONSOLIDATING"
    else:
        market_vs_news_alignment = "NEUTRAL_MARKET_DRIVEN"

    return {
        "status": "ACTIVE",
        "is_sufficient": True,
        "window_hours": window_hours,
        "evaluated_at": now.isoformat(),
        "total_fresh_scanned": total_fresh_scanned,
        "distinct_clusters_count": distinct_clusters_count,
        "relevant_fresh_count": len(relevant_evaluated),
        "message": (
            f"Active live news consensus derived from {distinct_clusters_count} distinct fresh story cluster(s) "
            f"over the past {window_hours} hours. Primary macro driver: {max(driver_counts, key=driver_counts.get)}."
        ),
        "net_signal": net_signal,
        "net_confidence": net_confidence,
        "bullish_weight": bullish_weight,
        "bearish_weight": bearish_weight,
        "mixed_weight": mixed_weight,
        "market_vs_news_alignment": market_vs_news_alignment,
        "driver_breakdown": driver_counts,
        "directional_breakdown": directional_counts,
        "market_reference": {
            "xauusd": market.get("xauusd"),
            "xauusd_change_24h_pct": xauusd_change_pct,
            "usdinr": market.get("usdinr"),
        },
        "representative_articles": cluster_representatives[:25],
    }
