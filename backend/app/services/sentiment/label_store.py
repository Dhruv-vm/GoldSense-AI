from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.research import (
    NewsArticleRecord,
    NewsCluster,
    NewsCollectionRun,
    NewsLabelRecord,
)
from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    COLLECTOR_VERSION,
    ProvenanceStatus,
    QUERY_VERSION,
    SENTIMENT_VERSION,
    _headline_token_set,
    _jaccard,
    compute_canonical_url,
    compute_content_fingerprint,
    compute_story_cluster_id,
    extract_story_cluster_key,
    headlines_should_merge,
    normalize_language,
    parse_utc_iso,
)
from app.services.sentiment.schemas import GoldSentimentResult, NewsArticle


def compute_label_hash(
    *,
    story_cluster_id: str,
    sentiment_version: str,
    model_name: str,
    gold_impact: str,
    driver: str,
    is_price_report: bool,
    model_digest: str | None = None,
) -> str:
    payload = (
        f"{story_cluster_id}|{sentiment_version}|{model_name}|{model_digest or ''}|"
        f"{gold_impact}|{driver}|{int(is_price_report)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _classifier_implementation_digest(fn: Callable[..., Any]) -> str:
    """
    Deterministic AST-based digest of the active classifier implementation (F-03, A3-6, A3-FINAL-7).

    Covers the evaluator function AST AND the full AST of its defining module plus
    `gold_impact` (rule tables, semantic config, negation/entity/event logic, helpers),
    with ALL comments and docstrings stripped. Does NOT depend on Python bytecode
    or PYTHONHASHSEED, and ignores comment/docstring-only edits.
    """
    import app.services.sentiment.gold_impact as _gold_impact_mod
    from app.services.sentiment.provenance import canonicalize_python_source_ast

    parts: list[str] = [SENTIMENT_VERSION]
    try:
        parts.append(canonicalize_python_source_ast(inspect.getsource(fn)))
    except Exception:
        parts.append(f"<nosource:{getattr(fn, '__module__', '')}.{getattr(fn, '__qualname__', repr(fn))}>")

    modules: list[Any] = []
    fn_mod = inspect.getmodule(fn)
    if fn_mod is not None:
        modules.append(fn_mod)
    if _gold_impact_mod not in modules:
        modules.append(_gold_impact_mod)
    for m in modules:
        try:
            parts.append(canonicalize_python_source_ast(inspect.getsource(m)))
        except Exception:
            parts.append(f"<nosource-module:{getattr(m, '__name__', '')}>")

    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _aggregate_cluster_label(
    *,
    story_cluster_id: str,
    member_impacts: list[dict[str, Any]],
    sent_version: str,
    model_name: str,
    model_digest: str | None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """
    NEW-1 Deterministic Cluster-Level Aggregation:
    Combines all member article classifications inside one story cluster into a single
    deterministic cluster-level label so multiple syndicated/reworded copies never emit
    conflicting duplicate label rows or roll back the collection transaction.
    """
    non_price = [m for m in member_impacts if not m.get("is_price_report")]
    pool = non_price if non_price else member_impacts
    all_price = len(non_price) == 0

    impacts_set = {str(m.get("gold_impact") or "UNKNOWN").upper() for m in pool}
    conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    if all_price:
        agg_impact = "NEUTRAL"
        agg_driver = "GOLD_PRICE_REPORT"
        agg_conf = "MEDIUM"
        agg_tone = "NEUTRAL"
        agg_surprise = "UNKNOWN"
        agg_rationale = "All cluster members are routine descriptive bullion price reports."
    elif "BULLISH" in impacts_set and "BEARISH" in impacts_set:
        agg_impact = "MIXED"
        agg_conf = "MEDIUM"
        best = max(pool, key=lambda m: conf_rank.get(str(m.get("confidence", "LOW")).upper(), 1))
        agg_driver = str(best.get("driver") or "OTHER_MACRO")
        agg_tone = "NEUTRAL"
        agg_surprise = str(best.get("surprise") or "UNKNOWN")
        agg_rationale = "Conflicting directional implications across cluster member articles."
    elif "BULLISH" in impacts_set:
        bulls = [m for m in pool if str(m.get("gold_impact")).upper() == "BULLISH"]
        best = max(bulls, key=lambda m: conf_rank.get(str(m.get("confidence", "LOW")).upper(), 1))
        agg_impact = "BULLISH"
        agg_driver = str(best.get("driver") or "UNKNOWN")
        agg_conf = str(best.get("confidence") or "MEDIUM")
        agg_tone = str(best.get("general_tone") or "UNKNOWN")
        agg_surprise = str(best.get("surprise") or "UNKNOWN")
        agg_rationale = str(best.get("evidence_rationale") or "")
    elif "BEARISH" in impacts_set:
        bears = [m for m in pool if str(m.get("gold_impact")).upper() == "BEARISH"]
        best = max(bears, key=lambda m: conf_rank.get(str(m.get("confidence", "LOW")).upper(), 1))
        agg_impact = "BEARISH"
        agg_driver = str(best.get("driver") or "UNKNOWN")
        agg_conf = str(best.get("confidence") or "MEDIUM")
        agg_tone = str(best.get("general_tone") or "UNKNOWN")
        agg_surprise = str(best.get("surprise") or "UNKNOWN")
        agg_rationale = str(best.get("evidence_rationale") or "")
    elif "MIXED" in impacts_set:
        mixes = [m for m in pool if str(m.get("gold_impact")).upper() == "MIXED"]
        best = max(mixes, key=lambda m: conf_rank.get(str(m.get("confidence", "LOW")).upper(), 1))
        agg_impact = "MIXED"
        agg_driver = str(best.get("driver") or "UNKNOWN")
        agg_conf = str(best.get("confidence") or "MEDIUM")
        agg_tone = str(best.get("general_tone") or "UNKNOWN")
        agg_surprise = str(best.get("surprise") or "UNKNOWN")
        agg_rationale = str(best.get("evidence_rationale") or "")
    elif "NEUTRAL" in impacts_set:
        neus = [m for m in pool if str(m.get("gold_impact")).upper() == "NEUTRAL"]
        best = neus[0]
        agg_impact = "NEUTRAL"
        agg_driver = str(best.get("driver") or "UNKNOWN")
        agg_conf = str(best.get("confidence") or "MEDIUM")
        agg_tone = str(best.get("general_tone") or "NEUTRAL")
        agg_surprise = str(best.get("surprise") or "UNKNOWN")
        agg_rationale = str(best.get("evidence_rationale") or "")
    else:
        best = pool[0]
        agg_impact = "UNKNOWN"
        agg_driver = str(best.get("driver") or "UNKNOWN")
        agg_conf = "LOW"
        agg_tone = str(best.get("general_tone") or "UNKNOWN")
        agg_surprise = str(best.get("surprise") or "UNKNOWN")
        agg_rationale = str(best.get("evidence_rationale") or "")

    l_hash = compute_label_hash(
        story_cluster_id=story_cluster_id,
        sentiment_version=sent_version,
        model_name=model_name,
        model_digest=model_digest,
        gold_impact=agg_impact,
        driver=agg_driver,
        is_price_report=all_price,
    )
    return {
        "sentiment_version": sent_version,
        "model_name": model_name,
        "model_digest": model_digest,
        "prompt_version": prompt_version,
        "general_tone": agg_tone,
        "gold_impact": agg_impact,
        "driver": agg_driver,
        "surprise": agg_surprise,
        "is_price_report": all_price,
        "confidence": agg_conf,
        "evidence_rationale": agg_rationale,
        "label_hash": l_hash,
    }


def _resolve_persistent_cluster_id_db(
    db: Session,
    *,
    canonical_url: str,
    title: str,
    pub_dt: datetime,
    suggested_cid: str | None,
    suggested_key: str | None,
    window_hours: float = 36.0,
) -> tuple[str, str]:
    """
    NEW-5: Resolve a stable, time-bounded `story_cluster_id` against DB state:
      1. If `canonical_url` is already stored in `news_articles`, return its permanent `story_cluster_id`.
      2. Else search existing `news_clusters` anchored within +/-36h with matching key or Jaccard >= 0.70.
      3. Else return `suggested_cid` (or time-bounded `compute_story_cluster_id`).
    """
    existing_art = db.execute(
        select(NewsArticleRecord).where(NewsArticleRecord.canonical_url == canonical_url)
    ).scalar_one_or_none()
    if existing_art is not None and existing_art.story_cluster_id:
        return existing_art.story_cluster_id, suggested_key or extract_story_cluster_key(title)

    ckey = suggested_key or extract_story_cluster_key(title)
    lo = pub_dt - timedelta(hours=window_hours)
    hi = pub_dt + timedelta(hours=window_hours)

    open_clusters = db.execute(
        select(NewsCluster)
        .where(
            NewsCluster.latest_published_at.is_not(None),
            NewsCluster.latest_published_at >= lo,
            NewsCluster.latest_published_at <= hi,
        )
        # Deterministic candidate order (no reliance on DB heap order).
        .order_by(NewsCluster.latest_published_at.desc(), NewsCluster.story_cluster_id.asc())
    ).scalars().all()

    best: tuple[float, NewsCluster] | None = None
    for clu in open_clusters:
        anchor_dt = _to_utc(clu.latest_published_at) if clu.latest_published_at else pub_dt
        if abs((pub_dt - anchor_dt).total_seconds()) > window_hours * 3600.0:
            continue
        rep_title = clu.representative_title or ""
        merge, score = headlines_should_merge(title, rep_title) if rep_title else (clu.cluster_key == ckey, 1.0)
        if merge and (best is None or score > best[0]):
            best = (score, clu)
    if best is not None:
        return best[1].story_cluster_id, best[1].cluster_key

    if suggested_cid:
        # Never adopt a suggested ID that already belongs to a DIFFERENT stored story.
        taken = db.execute(
            select(NewsCluster).where(NewsCluster.story_cluster_id == suggested_cid)
        ).scalar_one_or_none()
        if taken is None or not taken.representative_title or headlines_should_merge(title, taken.representative_title)[0]:
            return suggested_cid, ckey
    cid, key = compute_story_cluster_id(title, pub_dt, CLUSTER_VERSION)
    return cid, key


def persist_news_collection_to_db(
    db: Session,
    *,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    status: str,
    articles: list[NewsArticle],
    health: dict[str, Any],
    stats: dict[str, int],
    label_created_at: datetime | None = None,
    sentiment_result_overrides: dict[str, GoldSentimentResult] | None = None,
) -> dict[str, int]:
    """
    Durably persist NewsCollectionRun, NewsCluster, NewsArticleRecord, and cluster-aggregated
    append-only NewsLabelRecord rows.

    Fixes NEW-1 & NEW-5:
      - Resolves stable DB-persistent cluster IDs across runs without drift.
      - Groups articles by `story_cluster_id` and emits at most ONE deterministic cluster label per run.
      - Records actual `model_digest` & implementation-versioned `sentiment_version` so classifier
        changes always create distinguishable versions.
      - Isolates per-article classification errors cleanly so run health is always persisted.
    """
    label_ts = _to_utc(label_created_at or datetime.now(timezone.utc))
    impl_digest = _classifier_implementation_digest(evaluate_gold_impact)
    effective_rule_version = f"{SENTIMENT_VERSION}:{impl_digest[:6]}"

    articles_inserted = 0
    labels_appended = 0
    label_errors: list[str] = []

    # 1. Persist clusters & articles first, tracking cluster -> articles cleanly
    cluster_articles: dict[str, list[tuple[NewsArticle, NewsArticleRecord, datetime]]] = {}

    for art in articles:
        pub_dt = _to_utc(art.published_at)
        first_seen = _to_utc(art.first_seen_at or art.ingested_at or label_ts)
        c_url = (art.canonical_url or compute_canonical_url(art.url))[:1024]
        if not c_url:
            continue

        story_cid, ckey = _resolve_persistent_cluster_id_db(
            db,
            canonical_url=c_url,
            title=art.title,
            pub_dt=pub_dt,
            suggested_cid=art.story_cluster_id,
            suggested_key=art.cluster_key,
        )
        # Keep caller object synced for downstream logging if inspected
        art.story_cluster_id = story_cid
        art.cluster_key = ckey

        cluster_row = db.execute(
            select(NewsCluster).where(NewsCluster.story_cluster_id == story_cid)
        ).scalar_one_or_none()
        if cluster_row is None:
            cluster_row = NewsCluster(
                story_cluster_id=story_cid,
                cluster_key=ckey[:255],
                cluster_version=art.cluster_version or CLUSTER_VERSION,
                first_seen_at=first_seen,
                latest_published_at=pub_dt,
                representative_title=art.title,
                article_count=0,
            )
            db.add(cluster_row)
            db.flush()
        else:
            # Preserve earliest first_seen_at monotonically; keep bounded anchor timestamps.
            if cluster_row.first_seen_at is None or first_seen < _to_utc(cluster_row.first_seen_at):
                cluster_row.first_seen_at = first_seen

        art_row = db.execute(
            select(NewsArticleRecord).where(NewsArticleRecord.canonical_url == c_url)
        ).scalar_one_or_none()
        if art_row is None:
            art_row = NewsArticleRecord(
                canonical_url=c_url,
                url=art.url,
                title=art.title,
                source=art.source or "unknown",
                language=normalize_language(art.language),
                published_at=pub_dt,
                first_seen_at=first_seen,
                content_fingerprint=art.content_fingerprint or compute_content_fingerprint(art.title, c_url),
                query_id=art.query_id,
                query_version=art.query_version or QUERY_VERSION,
                collector_version=art.collector_version or COLLECTOR_VERSION,
                provenance_status=art.provenance_status or ProvenanceStatus.VERIFIED_SOURCE.value,
                story_cluster_id=story_cid,
            )
            db.add(art_row)
            db.flush()
            articles_inserted += 1
            cluster_row.article_count = int(cluster_row.article_count or 0) + 1

        cluster_articles.setdefault(story_cid, []).append((art, art_row, pub_dt))

    # 2. Classify and aggregate deterministically ONCE per cluster in this run (NEW-1).
    #    Collect label candidates first so NewsCollectionRun (immutable) is flushed with final
    #    health status BEFORE inserting NewsLabelRecord rows referencing collection_run_id.
    overrides = sentiment_result_overrides or {}
    pending_labels: list[dict[str, Any]] = []
    for story_cid, new_members in cluster_articles.items():
        # Include any already-persisted members of this cluster so re-sighting one copy never flips cluster consensus!
        all_db_members = db.execute(
            select(NewsArticleRecord).where(NewsArticleRecord.story_cluster_id == story_cid)
        ).scalars().all()

        rep_article_id = new_members[0][1].id
        rule_impacts: list[dict[str, Any]] = []
        override_groups: dict[tuple[str, str, str | None, str | None], list[dict[str, Any]]] = {}

        for db_art in sorted(all_db_members, key=lambda r: (_to_utc(r.published_at), r.id)):
            try:
                rule_impacts.append(
                    evaluate_gold_impact(
                        title=db_art.title,
                        published_at=_to_utc(db_art.published_at),
                        reference_time=label_ts,
                    )
                )
            except Exception as exc:
                label_errors.append(f"cluster={story_cid} art_id={db_art.id}: {exc}")
            override = overrides.get(db_art.canonical_url)
            if override is not None:
                key = (override.model_name, override.sentiment_version, override.model_digest, override.prompt_version)
                override_groups.setdefault(key, []).append(
                    {
                        "general_tone": override.general_tone.value,
                        "gold_impact": override.gold_impact.value,
                        "driver": override.driver.value,
                        "surprise": override.surprise.value,
                        "is_price_report": bool(override.is_price_report),
                        "confidence": override.confidence,
                        "evidence_rationale": override.evidence_rationale,
                    }
                )

        label_jobs: list[tuple[list[dict[str, Any]], str, str, str | None, str | None]] = []
        if rule_impacts:
            label_jobs.append((rule_impacts, effective_rule_version, "deterministic_rules_v2", impl_digest, None))
        for (o_model, o_ver, o_digest, o_prompt), impacts in sorted(
            override_groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])
        ):
            label_jobs.append((impacts, o_ver, o_model, o_digest, o_prompt))

        for impacts, sent_ver, model_name, m_digest, p_ver in label_jobs:
            agg = _aggregate_cluster_label(
                story_cluster_id=story_cid,
                member_impacts=impacts,
                sent_version=sent_ver,
                model_name=model_name,
                model_digest=m_digest,
                prompt_version=p_ver,
            )

            latest_existing = db.execute(
                select(NewsLabelRecord)
                .where(
                    NewsLabelRecord.story_cluster_id == story_cid,
                    NewsLabelRecord.model_name == model_name,
                )
                .order_by(NewsLabelRecord.label_created_at.desc(), NewsLabelRecord.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if (
                latest_existing is not None
                and latest_existing.sentiment_version == agg["sentiment_version"]
                and latest_existing.label_hash == agg["label_hash"]
            ):
                continue

            same_ts_existing = db.execute(
                select(NewsLabelRecord).where(
                    NewsLabelRecord.story_cluster_id == story_cid,
                    NewsLabelRecord.sentiment_version == agg["sentiment_version"],
                    NewsLabelRecord.model_name == model_name,
                    NewsLabelRecord.label_created_at == label_ts,
                )
            ).scalar_one_or_none()
            if same_ts_existing is not None:
                continue

            pending_labels.append(
                {
                    "rep_article_id": rep_article_id,
                    "story_cid": story_cid,
                    "agg": agg,
                }
            )

    # 3. Persist immutable NewsCollectionRun health BEFORE appending NewsLabelRecord rows
    final_status = "PARTIAL_FAILURE" if (label_errors and status == "SUCCESS") else status
    err_msgs = [str(g.get("error")) for g in health.get("groups", []) if g.get("error")] + label_errors
    existing_run = db.execute(
        select(NewsCollectionRun).where(NewsCollectionRun.run_id == run_id)
    ).scalar_one_or_none()
    if existing_run is None:
        meta = dict(health or {})
        if label_errors:
            meta["label_errors"] = label_errors
        db.add(
            NewsCollectionRun(
                run_id=run_id,
                started_at=_to_utc(started_at),
                completed_at=_to_utc(completed_at),
                status=final_status,
                query_version=str(health.get("query_version") or QUERY_VERSION),
                collector_version=str(health.get("collector_version") or COLLECTOR_VERSION),
                cluster_version=str(health.get("cluster_version") or CLUSTER_VERSION),
                queries_attempted=int(health.get("queries_attempted", 0)),
                queries_succeeded=int(health.get("queries_succeeded", 0)),
                queries_failed=int(health.get("queries_failed", 0)),
                raw_fetched=int(health.get("raw_fetched", len(articles))),
                unique_collected=int(health.get("unique_collected", len(articles))),
                new_archive_count=int(stats.get("new_archive_count", 0)),
                live_count=int(stats.get("live_count", 0)),
                error_summary="; ".join(err_msgs) or None,
                metadata_json=meta,
            )
        )
        db.flush()

    avail_ts = max(label_ts, _to_utc(completed_at))
    for item in pending_labels:
        agg = item["agg"]
        db.add(
            NewsLabelRecord(
                article_id=item["rep_article_id"],
                story_cluster_id=item["story_cid"],
                collection_run_id=run_id,
                classification_scope="CLUSTER",
                label_created_at=label_ts,
                available_at=avail_ts,
                sentiment_version=agg["sentiment_version"],
                model_name=agg["model_name"],
                model_digest=agg["model_digest"],
                prompt_version=agg["prompt_version"],
                classifier_impl_version=impl_digest if agg["model_name"] == "deterministic_rules_v2" else agg["sentiment_version"],
                general_tone=agg["general_tone"],
                gold_impact=agg["gold_impact"],
                driver=agg["driver"],
                surprise=agg["surprise"],
                is_price_report=bool(agg["is_price_report"]),
                feature_eligible=True,
                label_hash=agg["label_hash"],
                confidence=agg["confidence"],
                evidence_rationale=agg["evidence_rationale"],
                is_human_verified=False,
            )
        )
        db.flush()
        labels_appended += 1

    db.commit()
    return {
        "articles_inserted": articles_inserted,
        "labels_appended": labels_appended,
        "label_errors": len(label_errors),
    }


def append_label_to_jsonl(
    jsonl_path: Path,
    *,
    story_cluster_id: str,
    label_created_at: datetime,
    sentiment_version: str,
    model_name: str,
    gold_impact: str,
    driver: str,
    is_price_report: bool,
    confidence: str,
    general_tone: str = "UNKNOWN",
    surprise: str = "UNKNOWN",
    prompt_version: str | None = None,
    model_digest: str | None = None,
) -> bool:
    """
    Append an immutable versioned label record to local JSONL ledger idempotently:
    if an identical `(story_cluster_id, sentiment_version, model_name, label_hash)`
    is already present, do not emit duplicate lines.
    """
    ts = _to_utc(label_created_at)
    l_hash = compute_label_hash(
        story_cluster_id=story_cluster_id,
        sentiment_version=sentiment_version,
        model_name=model_name,
        model_digest=model_digest,
        gold_impact=gold_impact,
        driver=driver,
        is_price_report=is_price_report,
    )
    key = (story_cluster_id, sentiment_version, model_name, l_hash)
    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as rfh:
            for line in rfh:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing = json.loads(line)
                    ekey = (
                        existing.get("story_cluster_id"),
                        existing.get("sentiment_version"),
                        existing.get("model_name"),
                        existing.get("label_hash"),
                    )
                    if ekey == key:
                        return False
                except Exception:
                    continue

    record = {
        "story_cluster_id": story_cluster_id,
        "label_created_at": ts.isoformat(),
        "sentiment_version": sentiment_version,
        "model_name": model_name,
        "model_digest": model_digest,
        "prompt_version": prompt_version,
        "general_tone": general_tone,
        "gold_impact": gold_impact,
        "driver": driver,
        "surprise": surprise,
        "is_price_report": bool(is_price_report),
        "confidence": confidence,
        "label_hash": l_hash,
    }
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return True
