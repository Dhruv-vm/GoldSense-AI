"""Third-audit cluster/label attacks across collection runs (LOCAL temporary PostgreSQL, synthetic articles)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

import app.db.session as dbs
import app.models  # noqa
from app.models.research import NewsArticleRecord, NewsLabelRecord, NewsCollectionRun, NewsCluster
import app.services.sentiment.label_store as LS
from app.services.sentiment.schemas import NewsArticle
from app.services.sentiment.provenance import assign_story_clusters
from app.services.prediction.news_features import load_eligible_news_records_from_db, compute_news_features_at_cutoff

T0 = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


def mk(title, url, pub, seen):
    return NewsArticle(title=title, url=url, source="S", published_at=pub, language="en", ingested_at=seen, first_seen_at=seen)


def run(db, arts, at, rid):
    d = assign_story_clusters([{"published_at": a.published_at, "title": a.title} for a in arts])
    for a, x in zip(arts, d):
        a.story_cluster_id, a.cluster_key, a.cluster_version = x["story_cluster_id"], x["cluster_key"], x["cluster_version"]
    try:
        return LS.persist_news_collection_to_db(db, run_id=rid, started_at=at, completed_at=at, status="SUCCESS", articles=arts,
                                                health={"queries_attempted": 11, "queries_succeeded": 11}, stats={}, label_created_at=at)
    except Exception as e:
        db.rollback(); return "RUN FAILED " + type(e).__name__ + ": " + str(e).splitlines()[0][:100]


def cid(db, url):
    return db.execute(select(NewsArticleRecord.story_cluster_id).where(NewsArticleRecord.canonical_url.like(f"%{url}"))).scalar()


def main():
    db = dbs.SessionLocal()
    S = "Gold jumps as Fed signals rate cuts amid weak jobs data"
    # 1. overlapping batches: run1 [A], run2 [A, B(syndicated)], run3 [B, C(late-arriving, published earlier than A)]
    print("run1", run(db, [mk(S + " - Reuters", "https://ex.com/A", T0 - timedelta(hours=2), T0)], T0, "r1"))
    T1 = T0 + timedelta(hours=6)
    print("run2", run(db, [mk(S + " - Reuters", "https://ex.com/A", T0 - timedelta(hours=2), T1), mk(S + " - Mint", "https://ex.com/B", T0 - timedelta(hours=1), T1)], T1, "r2"))
    T2 = T0 + timedelta(hours=12)
    print("run3", run(db, [mk(S + " - Mint", "https://ex.com/B", T0 - timedelta(hours=1), T2), mk(S + " - ET", "https://ex.com/C", T0 - timedelta(hours=5), T2)], T2, "r3"))
    # URL change for the same article (tracking params / AMP)
    T3 = T0 + timedelta(hours=18)
    print("run4 url-change", run(db, [mk(S + " - Reuters", "https://ex.com/A?utm_source=x", T0 - timedelta(hours=2), T3), mk(S + " - Reuters", "https://ex.com/amp/A", T0 - timedelta(hours=2), T3)], T3, "r4"))
    ids = {u: cid(db, u) for u in ["/A", "/B", "/C", "/amp/A"]}
    print("cluster ids:", {k: (v[-8:] if v else None) for k, v in ids.items()}, "distinct:", len({v for v in ids.values() if v}))
    f = compute_news_features_at_cutoff(T3 + timedelta(minutes=1), *load_eligible_news_records_from_db(db, T3 + timedelta(minutes=1), model_name="deterministic_rules_v2"))
    print("one story -> n_clusters_relevant:", f.n_clusters_relevant)
    labs = db.execute(select(NewsLabelRecord.gold_impact, NewsLabelRecord.label_created_at).where(NewsLabelRecord.story_cluster_id == ids["/A"]).order_by(NewsLabelRecord.id)).all()
    print("labels for the story:", [(g, t.isoformat()[11:16]) for g, t in labs])

    # 2. cross-day bulletins (templated headlines on consecutive days)
    B0 = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
    for k in range(4):
        t = B0 + timedelta(days=k)
        run(db, [mk(f"Gold, silver prices today October {20 + k}: yellow metal edges higher in Chennai, Mumbai", f"https://ex.com/bul{k}", t, t + timedelta(hours=1))], t + timedelta(hours=1), f"b{k}")
    bids = [cid(db, f"/bul{k}") for k in range(4)]
    print("cross-day bulletins cluster ids:", [b[-6:] for b in bids], "distinct:", len(set(bids)))

    # 3. ambiguity: one new article matching two open clusters (DB iteration order decides)
    M0 = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)
    run(db, [mk("Gold slips as dollar firms ahead of US CPI data release", "https://ex.com/m1", M0, M0)], M0, "m1")
    run(db, [mk("Gold slips as dollar firms ahead of US PPI data release", "https://ex.com/m2", M0 + timedelta(hours=1), M0 + timedelta(hours=1))], M0 + timedelta(hours=1), "m2")
    print("near-duplicate distinct macro stories CPI vs PPI merged:", cid(db, "/m1") == cid(db, "/m2"))

    # 4. different stories sharing first-6-token boilerplate
    run(db, [mk("Gold price today in India: RBI hikes repo rate by 25 bps", "https://ex.com/q1", M0 + timedelta(days=1), M0 + timedelta(days=1)),
             mk("Gold price today in India: rupee hits record low", "https://ex.com/q2", M0 + timedelta(days=1, hours=1), M0 + timedelta(days=1, hours=1))],
        M0 + timedelta(days=1, hours=1), "q")
    print("unrelated boilerplate stories merged (RBI hike vs rupee low):", cid(db, "/q1") == cid(db, "/q2"),
          "label:", db.execute(select(NewsLabelRecord.gold_impact).where(NewsLabelRecord.story_cluster_id == cid(db, "/q1"))).scalars().all())
    print("runs recorded:", db.execute(select(func.count()).select_from(NewsCollectionRun)).scalar())
    db.close()


if __name__ == "__main__":
    main()
