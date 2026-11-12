from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.db.session as db_session
from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.label_store import (
    append_label_to_jsonl,
    persist_news_collection_to_db,
)
from app.services.sentiment.news_client import NewsClient, QUERY_GROUPS
from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    COLLECTOR_VERSION,
    QUERY_VERSION,
    assign_story_clusters,
)


def collect() -> int:
    project_root = Path(__file__).resolve().parents[1]
    archive_csv_path = project_root / "data/news/news_articles.csv"
    live_csv_path = project_root / "data/news/live_news.csv"
    labels_jsonl_path = project_root / "data/news/news_labels.jsonl"
    runs_log_path = project_root / "data/news/collection_runs.jsonl"

    lookback_hours = int(os.getenv("NEWS_LOOKBACK_HOURS", "24"))
    live_retention_hours = int(os.getenv("NEWS_LIVE_RETENTION_HOURS", "72"))
    enable_csv_mirror = os.getenv("ENABLE_CSV_MIRROR", "true").lower() in {"1", "true", "yes"}

    client = NewsClient()
    started_at = datetime.now(timezone.utc)
    articles = client.search_query_groups(
        groups=QUERY_GROUPS,
        lookback_hours=lookback_hours,
        max_records_per_group=15,
    )
    completed_at = datetime.now(timezone.utc)

    # Apply sliding-proximity clustering across bucket boundaries (F-16)
    if articles:
        clustered_dicts = assign_story_clusters(
            [{"published_at": a.published_at, "title": a.title, "idx": i} for i, a in enumerate(articles)],
            window_hours=36.0,
        )
        for art, cdict in zip(articles, clustered_dicts):
            art.story_cluster_id = cdict["story_cluster_id"]
            art.cluster_key = cdict["cluster_key"]
            art.cluster_version = cdict["cluster_version"]

    health = getattr(client, "last_collection_health", {}) or {}
    succeeded = int(health.get("queries_succeeded", 0))
    failed = int(health.get("queries_failed", 0))

    if succeeded == 0 and failed > 0:
        status = "FAILED"
    elif failed > 0:
        status = "PARTIAL_FAILURE"
    elif len(articles) == 0:
        status = "NO_NEW_NEWS"
    else:
        status = "SUCCESS"

    stats = {"new_archive_count": 0, "live_count": 0, "pruned_count": 0}
    if enable_csv_mirror and (articles or live_csv_path.exists()):
        stats = client.save_news_datasets(
            articles=articles,
            live_csv_path=live_csv_path,
            archive_csv_path=archive_csv_path,
            lookback_hours=lookback_hours,
            max_live_retention_hours=live_retention_hours,
        )

    run_id = f"news_run_{completed_at.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    label_ts = datetime.now(timezone.utc)

    # Durable DB persistence (F-03 / F-19): write collection run, clusters, articles, and append-only labels
    from app.services.ollama.classifier import OllamaGoldClassifier, is_ollama_enabled

    db = db_session.SessionLocal()
    try:
        db_stats = persist_news_collection_to_db(
            db,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            articles=articles,
            health=health,
            stats=stats,
            label_created_at=label_ts,
        )
        # F-21 / A3-FINAL-5: Optional local Ollama worker labels appended cleanly without touching deterministic rule labels
        if is_ollama_enabled() and articles:
            from app.models.bullion import CollectorRun
            clf = OllamaGoldClassifier()
            ollama_ok = 0
            ollama_failed: list[str] = []
            if clf.health_check():
                seen_cids: set[str] = set()
                for art in articles:
                    cid = art.story_cluster_id or ""
                    if not cid or cid in seen_cids:
                        continue
                    seen_cids.add(cid)
                    try:
                        clf.classify_and_persist(
                            db,
                            story_cluster_id=cid,
                            title=art.title,
                            source=art.source,
                            language=art.language or "en",
                        )
                        ollama_ok += 1
                    except Exception as exc:
                        # A3-7 / A3-FINAL-5: never poison session and never fall back to rules.
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        ollama_failed.append(f"{cid}: {exc}")
                        print(f"[news-collector] Ollama label skipped for cluster {cid}: {exc}")
                        continue
            else:
                ollama_failed.append("Ollama daemon health_check() failed")
            if ollama_ok > 0 or ollama_failed:
                try:
                    db.add(
                        CollectorRun(
                            collector_name="OLLAMA_NEWS_CLASSIFIER",
                            run_id=run_id,
                            status="FAILED" if (ollama_failed and ollama_ok == 0) else ("PARTIAL" if ollama_failed else "SUCCESS"),
                            records_extracted=ollama_ok + len(ollama_failed),
                            records_inserted=ollama_ok,
                            records_quarantined=len(ollama_failed),
                            error_message="; ".join(ollama_failed)[:1000] if ollama_failed else None,
                        )
                    )
                    db.commit()
                except Exception:
                    db.rollback()
    finally:
        db.close()

    if enable_csv_mirror:
        for art in articles:
            impact = evaluate_gold_impact(title=art.title, published_at=art.published_at, reference_time=label_ts)
            append_label_to_jsonl(
                labels_jsonl_path,
                story_cluster_id=art.story_cluster_id or impact["story_cluster_id"],
                label_created_at=label_ts,
                sentiment_version=impact["sentiment_version"],
                model_name="deterministic_rules_v2",
                gold_impact=impact["gold_impact"],
                driver=impact["driver"],
                is_price_report=bool(impact["is_price_report"]),
                confidence=impact["confidence"],
                general_tone=impact["general_tone"],
                surprise=impact["surprise"],
            )

        run_record = {
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "status": status,
            "query_version": QUERY_VERSION,
            "collector_version": COLLECTOR_VERSION,
            "cluster_version": CLUSTER_VERSION,
            "queries_attempted": health.get("queries_attempted", len(QUERY_GROUPS)),
            "queries_succeeded": succeeded,
            "queries_failed": failed,
            "raw_fetched": health.get("raw_fetched", len(articles)),
            "unique_collected": len(articles),
            "new_archive_count": stats["new_archive_count"],
            "live_count": stats["live_count"],
            "pruned_count": stats["pruned_count"],
            "db_articles_inserted": db_stats["articles_inserted"],
            "db_labels_appended": db_stats["labels_appended"],
            "errors": [g["error"] for g in health.get("groups", []) if g.get("error")],
        }
        runs_log_path.parent.mkdir(parents=True, exist_ok=True)
        with runs_log_path.open("a", encoding="utf-8") as rf:
            rf.write(json.dumps(run_record) + "\n")

    print(
        f"[NEWS COLLECT] status={status} collected={len(articles)} "
        f"db_articles={db_stats['articles_inserted']} db_labels={db_stats['labels_appended']} "
        f"failed_queries={failed}"
    )
    return 1 if status == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(collect())
