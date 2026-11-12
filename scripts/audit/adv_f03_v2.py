# UPDATED VARIANT of adv_f03.py (2026-11-11 final verification). Original is unchanged.
# Changes (marked [V2]; the second pair uses its own URLs): (1) a SECOND identical rerun to test true idempotency, because the original
# "identical rerun" immediately follows a rule-flip revert and so legitimately appends; (2) the version-string
# line is computed instead of hard-coded; (3) the ping-pong attack runs on BOTH the original pair (two
# different events, which must now split) and a same-story reworded pair (which must merge and stay stable).
"""Second-audit adversarial test for F-03 label provenance on a LOCAL temporary PostgreSQL."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json, tempfile

from sqlalchemy import select, func

from _db_guard import ensure_disposable_audit_db
ensure_disposable_audit_db()

import app.db.session as dbs
import app.models  # noqa
from app.models.research import NewsLabelRecord, NewsArticleRecord, NewsCollectionRun
import app.services.sentiment.label_store as LS
from app.services.sentiment.schemas import NewsArticle
from app.services.sentiment.provenance import assign_story_clusters, compute_story_cluster_id
from app.services.prediction.news_features import load_eligible_news_records_from_db, compute_news_features_at_cutoff

T1 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)


def art(title, url, pub, seen):
    return NewsArticle(title=title, url=url, source="Test", published_at=pub, language="en",
                       ingested_at=seen, first_seen_at=seen)


def run(db, arts, at, status="SUCCESS"):
    dicts = assign_story_clusters([{"published_at": a.published_at, "title": a.title} for a in arts], window_hours=36.0)
    for a, d in zip(arts, dicts):
        a.story_cluster_id, a.cluster_key, a.cluster_version = d["story_cluster_id"], d["cluster_key"], d["cluster_version"]
    try:
        return LS.persist_news_collection_to_db(db, run_id=f"run_{at.isoformat()}", started_at=at, completed_at=at, status=status,
            articles=arts, health={"queries_attempted": 11, "queries_succeeded": 11, "queries_failed": 0}, stats={}, label_created_at=at), dicts
    except Exception as e:
        db.rollback(); print("   !! RUN FAILED at", at.isoformat(), type(e).__name__); return {"labels_appended": "FAILED", "articles_inserted": "FAILED"}, dicts


def feats(db, T):
    recs, runs = load_eligible_news_records_from_db(db, cutoff_time=T)
    f = compute_news_features_at_cutoff(cutoff_time=T, records=recs, collection_runs=runs, lookback_hours=24, require_verified_availability=True)
    return f, len(recs)


def main():
    db = dbs.SessionLocal()
    titles = ["Gold rises as dollar weakens after jobs data",
              "Fed cuts rates in surprise move, gold jumps",
              "Rupee falls to record low against dollar"]
    A = [art(t, f"https://ex.com/a{i}", T1 - timedelta(hours=2), T1) for i, t in enumerate(titles)]
    s1, _ = run(db, A, T1)
    f_before, n_before = feats(db, T1 + timedelta(hours=1))
    print("F-03 run1:", s1, "| feature@T1+1h net_impact:", f_before.net_impact, "coverage:", f_before.coverage_ok, "records:", n_before)

    # flip classifier rules, re-sight the same articles 6h later (same SENTIMENT_VERSION string)
    orig = LS.evaluate_gold_impact
    def flipped(*a, **k):
        r = orig(*a, **k); m = {"BULLISH": "BEARISH", "BEARISH": "BULLISH"}; r["gold_impact"] = m.get(r["gold_impact"], r["gold_impact"]); return r
    LS.evaluate_gold_impact = flipped
    T2 = T1 + timedelta(hours=6)
    A2 = [art(t, f"https://ex.com/a{i}", T1 - timedelta(hours=2), T2) for i, t in enumerate(titles)]
    s2, _ = run(db, A2, T2)
    LS.evaluate_gold_impact = orig
    f_hist, _ = feats(db, T1 + timedelta(hours=1))
    f_after, n_after = feats(db, T2 + timedelta(hours=1))
    print("F-03 sign-flip replay: historical feature@T1+1h", f_before.net_impact, "->", f_hist.net_impact,
          "| feature@T2+1h:", f_after.net_impact, "records:", n_after, "| labels appended run2:", s2["labels_appended"])
    vers = db.execute(select(NewsLabelRecord.sentiment_version, func.count()).group_by(NewsLabelRecord.sentiment_version)).all()
    print("   label rows by sentiment_version:", vers, "[V2] distinct versions:", len(vers), "(>1 means the rule change IS reflected)")

    # idempotency: identical re-run
    s3, _ = run(db, [art(t, f"https://ex.com/a{i}", T1 - timedelta(hours=2), T2 + timedelta(hours=6)) for i, t in enumerate(titles)], T2 + timedelta(hours=6))
    print("F-03 identical rerun labels appended:", s3["labels_appended"], "(follows the flip revert -> expected to append)")
    s3b, _ = run(db, [art(t, f"https://ex.com/a{i}", T1 - timedelta(hours=2), T2 + timedelta(hours=7)) for i, t in enumerate(titles)], T2 + timedelta(hours=7))
    print("[V2] F-03 TRUE identical rerun (no rule change) labels appended:", s3b["labels_appended"], "(expect 0)")

    # cluster-ID stability across overlapping runs: an earlier member of the same story appears in run 2
    T3 = T1 + timedelta(days=3)
    X = art("Gold price climbs on safe haven demand amid Middle East tensions", "https://ex.com/x1", T3 - timedelta(hours=1), T3)
    (_, d1) = run(db, [X], T3)
    T4 = T3 + timedelta(hours=6)
    Y = art("Gold price climbs on safe haven demand amid Middle East tensions - Reuters", "https://ex.com/y1", T3 - timedelta(hours=3), T4)
    X2 = art(X.title, X.url, X.published_at, T4)
    (_, d2) = run(db, [Y, X2], T4)
    print("F-16/F-03 cluster ids for article X: run1", d1[0]["story_cluster_id"], "run2", [d["story_cluster_id"] for d in d2])
    f4, _ = feats(db, T4 + timedelta(minutes=5))
    print("   one story -> n_clusters_relevant at T4:", f4.n_clusters_relevant)

    # label ping-pong: two differently-worded members of one cluster, re-sighted every run
    T5 = T1 + timedelta(days=6)
    for tag, P1, P2 in (("original pair (different events)", "Gold silver prices India market update Fed cuts rates", "Gold silver prices India market update dollar strengthens sharply"),
                        ("[V2] same-story reworded pair", "Gold silver prices India market update Fed cuts rates, dollar slips", "Gold silver prices India market update Fed cuts rates, dollar strengthens")):
        T5 = T5 + timedelta(days=3)
        counts = []
        for k in range(4):
            tk = T5 + timedelta(hours=6 * k)
            st, dd = run(db, [art(P1, f"https://ex.com/p1{tag[:4]}", T5 - timedelta(hours=1), tk), art(P2, f"https://ex.com/p2{tag[:4]}", T5 - timedelta(minutes=30), tk)], tk)
            counts.append(st["labels_appended"])
        cids = sorted({x["story_cluster_id"] for x in dd})
        seq = [r.gold_impact for r in db.execute(select(NewsLabelRecord).where(NewsLabelRecord.story_cluster_id.in_(cids)).order_by(NewsLabelRecord.id)).scalars()]
        print(f"F-03 two-member re-sightings, {tag}: clusters={len(cids)} labels appended per run", counts, "label history:", seq)

    # time-less cluster id fallback
    a, _ = compute_story_cluster_id("Gold Rate Today: Check 22K, 24K gold prices in Delhi Mumbai", datetime(2026, 9, 1, tzinfo=timezone.utc))
    b, _ = compute_story_cluster_id("Gold Rate Today: Check 22K, 24K gold prices in Delhi Mumbai", datetime(2026, 11, 30, tzinfo=timezone.utc))
    print("F-16 compute_story_cluster_id 90 days apart -> same id:", a == b)

    # JSONL idempotency
    p = Path(tempfile.mkdtemp()) / "labels.jsonl"
    for _ in range(2):
        LS.append_label_to_jsonl(p, story_cluster_id="c", label_created_at=T1, sentiment_version="v", model_name="m",
                                 gold_impact="BULLISH", driver="USD", is_price_report=False, confidence="HIGH")
    print("JSONL identical append twice -> lines:", sum(1 for _ in p.open()))
    db.close()


if __name__ == "__main__":
    main()
