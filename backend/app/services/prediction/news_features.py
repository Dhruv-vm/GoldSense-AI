from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.research import NewsArticleRecord, NewsCollectionRun, NewsLabelRecord
from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    ProvenanceStatus,
    SENTIMENT_VERSION,
    parse_utc_iso,
)

NEWS_FEATURES_VERSION = "NEWS_FEATURES_V2"


@dataclass(frozen=True)
class EligibleNewsRecord:
    story_cluster_id: str
    title: str
    published_at: datetime
    first_seen_at: datetime | None
    label_created_at: datetime | None
    provenance_status: str
    gold_impact: str
    driver: str
    is_price_report: bool
    confidence: str
    source: str = ""
    language: str = "en"
    sentiment_version: str = SENTIMENT_VERSION
    model_name: str = ""
    label_hash: str = ""


@dataclass(frozen=True)
class CutoffNewsFeatures:
    cutoff_time: str
    lookback_hours: int
    feature_version: str
    cluster_version: str
    sentiment_version: str
    n_clusters_relevant: int
    # F-10: Nullable when coverage fails or zero non-price clusters exist (never fake neutral 0.0)
    net_impact: float | None
    unknown_share: float | None
    coverage_ok: bool
    feature_hash: str
    # Diagnostic counts
    total_eligible_articles: int
    excluded_price_report_clusters: int
    bullish_clusters: int
    bearish_clusters: int
    mixed_clusters: int
    neutral_clusters: int
    unknown_clusters: int
    collection_status_in_window: str

    def to_model_dict(self) -> dict[str, float | int | bool | None]:
        """Return strictly the compact pre-registered news feature vector."""
        return {
            "n_clusters_relevant": self.n_clusters_relevant,
            "net_impact": self.net_impact,
            "unknown_share": self.unknown_share,
            "coverage_ok": int(self.coverage_ok),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_news_features_at_cutoff(
    cutoff_time: datetime,
    records: Iterable[EligibleNewsRecord],
    collection_runs: Iterable[dict[str, Any]] | None = None,
    lookback_hours: int = 24,
    min_relevant_clusters_for_coverage: int = 2,
    require_verified_availability: bool = True,
    require_collection_run: bool = True,
) -> CutoffNewsFeatures:
    """
    Compute leakage-free point-in-time news features strictly from STORED labels at cutoff `T`:
    - Excludes SYNTHETIC_FIXTURE, DUPLICATE, INVALID, and (when strict) unverified historical rows.
    - Enforces `first_seen_at <= T` and `label_created_at <= T` (selecting only the latest
      stored label `<= T` per `story_cluster_id`, so classifier edits NEVER mutate historical cutoffs).
    - Excludes routine descriptive price reports (`is_price_report` / `GOLD_PRICE_REPORT`).
    - Requires healthy collector coverage in window; when missing/failed, returns
      `coverage_ok=False`, `net_impact=None`, `unknown_share=None` (never neutral 0.0).
    """
    cutoff_utc = _to_utc(cutoff_time)
    window_start = cutoff_utc - timedelta(hours=lookback_hours)

    # First select the latest valid STORED label per cluster strictly as of <= cutoff_utc (F-03)
    cluster_reps: dict[str, EligibleNewsRecord] = {}
    total_eligible_articles = 0
    conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    for rec in records:
        if rec.provenance_status in {
            ProvenanceStatus.SYNTHETIC_FIXTURE.value,
            ProvenanceStatus.DUPLICATE.value,
            ProvenanceStatus.INVALID.value,
        }:
            continue
        if require_verified_availability and rec.provenance_status != ProvenanceStatus.VERIFIED_SOURCE.value:
            continue
        if rec.first_seen_at is None or rec.label_created_at is None:
            continue

        first_seen_utc = _to_utc(rec.first_seen_at)
        label_created_utc = _to_utc(rec.label_created_at)

        # Strict temporal provenance gate: NEVER read future articles or future-created labels.
        if first_seen_utc > cutoff_utc or label_created_utc > cutoff_utc:
            continue
        if first_seen_utc < window_start:
            continue

        total_eligible_articles += 1
        cid = rec.story_cluster_id
        existing = cluster_reps.get(cid)
        if existing is None:
            cluster_reps[cid] = rec
        else:
            existing_label_utc = _to_utc(existing.label_created_at) if existing.label_created_at else cutoff_utc
            # Prefer newer label_created_at (still <= T), then confidence, then earliest seen.
            rec_key = (
                label_created_utc.timestamp(),
                conf_rank.get(rec.confidence.upper(), 1),
                -first_seen_utc.timestamp(),
            )
            ext_first = _to_utc(existing.first_seen_at) if existing.first_seen_at else cutoff_utc
            ext_key = (
                existing_label_utc.timestamp(),
                conf_rank.get(existing.confidence.upper(), 1),
                -ext_first.timestamp(),
            )
            if rec_key > ext_key:
                cluster_reps[cid] = rec

    excluded_price_reports = 0
    bullish = 0
    bearish = 0
    mixed = 0
    neutral = 0
    unknown = 0
    trace_tokens: list[str] = []

    for cid in sorted(cluster_reps.keys()):
        rep = cluster_reps[cid]
        if rep.is_price_report or rep.driver == "GOLD_PRICE_REPORT":
            excluded_price_reports += 1
            continue
        impact = (rep.gold_impact or "UNKNOWN").upper()
        trace_tokens.append(f"{cid}:{rep.label_hash or impact}:{rep.sentiment_version}")
        if impact == "BULLISH":
            bullish += 1
        elif impact == "BEARISH":
            bearish += 1
        elif impact == "MIXED":
            mixed += 1
        elif impact == "NEUTRAL":
            neutral += 1
        else:
            unknown += 1

    non_price_total = bullish + bearish + mixed + neutral + unknown

    # Collector run health gate strictly inside [window_start, cutoff_utc] (F-10)
    collection_status = "NO_RUN_RECORDED"
    collector_healthy = not require_collection_run
    if collection_runs is not None:
        relevant_runs: list[dict[str, Any]] = []
        for run in collection_runs:
            completed_dt = parse_utc_iso(str(run.get("completed_at") or run.get("started_at") or ""))
            if completed_dt is None:
                continue
            if window_start <= completed_dt <= cutoff_utc:
                relevant_runs.append(run)
        if relevant_runs:
            # Audit #3 residual: coverage is judged by the LATEST run in the window. An older
            # success followed by a newer FAILED/degraded run means the collector was not
            # healthy at the cutoff, so features are unavailable rather than silently stale.
            def _completed(r: dict[str, Any]) -> datetime:
                return parse_utc_iso(str(r.get("completed_at") or r.get("started_at") or "")) or window_start

            latest = max(relevant_runs, key=lambda r: (_completed(r), str(r.get("run_id") or "")))
            st = str(latest.get("status") or "UNKNOWN")
            att = int(latest.get("queries_attempted") or 0)
            suc = int(latest.get("queries_succeeded") or 0)
            if att > 0:
                ratio = suc / att
            else:
                ratio = 1.0 if st in {"SUCCESS", "NO_NEW_NEWS"} else 0.0

            if st in {"SUCCESS", "NO_NEW_NEWS", "PARTIAL_FAILURE"} and ratio >= 0.5:
                collection_status = {"SUCCESS": "OK"}.get(st, st)
                collector_healthy = True
            elif st == "FAILED":
                collection_status = "FAILED"
                collector_healthy = False
            else:
                collection_status = "DEGRADED_LOW_QUERY_COVERAGE"
                collector_healthy = False

    # F-10: Quiet healthy news day (collector succeeded with 0-1 clusters) is valid observed coverage
    # (neutral 0.0 if 0 clusters, avoiding selection bias toward only news-heavy days).
    # Failed or unrecorded collection remains unavailable (coverage_ok=False, net_impact=None).
    if require_collection_run:
        coverage_ok = collector_healthy
    else:
        coverage_ok = collector_healthy and (non_price_total >= min_relevant_clusters_for_coverage)

    dir_plus_unknown = bullish + bearish + unknown
    if not coverage_ok:
        net_impact: float | None = None
        unknown_share: float | None = None
    elif non_price_total == 0:
        net_impact = 0.0
        unknown_share = 0.0
    else:
        net_impact = round((bullish - bearish) / dir_plus_unknown, 4) if dir_plus_unknown > 0 else 0.0
        unknown_share = round(unknown / non_price_total, 4)

    hash_payload = json.dumps(
        {
            "cutoff": cutoff_utc.isoformat(),
            "lookback_hours": lookback_hours,
            "feature_version": NEWS_FEATURES_VERSION,
            "collection_status": collection_status,
            "clusters": trace_tokens,
        },
        sort_keys=True,
    )
    feature_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()[:32]

    return CutoffNewsFeatures(
        cutoff_time=cutoff_utc.isoformat(),
        lookback_hours=lookback_hours,
        feature_version=NEWS_FEATURES_VERSION,
        cluster_version=CLUSTER_VERSION,
        sentiment_version=SENTIMENT_VERSION,
        n_clusters_relevant=non_price_total,
        net_impact=net_impact,
        unknown_share=unknown_share,
        coverage_ok=coverage_ok,
        feature_hash=feature_hash,
        total_eligible_articles=total_eligible_articles,
        excluded_price_report_clusters=excluded_price_reports,
        bullish_clusters=bullish,
        bearish_clusters=bearish,
        mixed_clusters=mixed,
        neutral_clusters=neutral,
        unknown_clusters=unknown,
        collection_status_in_window=collection_status,
    )


def load_eligible_news_records_from_db(
    db: Session,
    cutoff_time: datetime,
    *,
    sentiment_version: str | None = None,
    model_name: str | None = None,
) -> tuple[list[EligibleNewsRecord], list[dict[str, Any]]]:
    """
    F-03 / F-19: Load persisted news articles joined with append-only STORED `news_labels`
    strictly satisfying `first_seen_at <= cutoff_time` AND `label_created_at <= cutoff_time`.
    Never recomputes classifier rules dynamically.
    """
    cutoff_utc = _to_utc(cutoff_time)

    stmt = (
        select(NewsArticleRecord, NewsLabelRecord)
        .join(NewsLabelRecord, NewsLabelRecord.story_cluster_id == NewsArticleRecord.story_cluster_id)
        .where(
            NewsArticleRecord.provenance_status == ProvenanceStatus.VERIFIED_SOURCE.value,
            NewsArticleRecord.first_seen_at.is_not(None),
            NewsArticleRecord.first_seen_at <= cutoff_utc,
            NewsLabelRecord.available_at <= cutoff_utc,
            NewsLabelRecord.label_created_at <= cutoff_utc,
            NewsLabelRecord.available_at >= NewsArticleRecord.first_seen_at,
            NewsLabelRecord.feature_eligible.is_(True),
        )
    )
    if sentiment_version:
        stmt = stmt.where(NewsLabelRecord.sentiment_version == sentiment_version)
    if model_name:
        stmt = stmt.where(NewsLabelRecord.model_name == model_name)

    rows = db.execute(stmt).all()
    records: list[EligibleNewsRecord] = []
    for art, lbl in rows:
        effective_avail = max(_to_utc(lbl.available_at), _to_utc(lbl.label_created_at))
        records.append(
            EligibleNewsRecord(
                story_cluster_id=lbl.story_cluster_id,
                title=art.title,
                published_at=_to_utc(art.published_at),
                first_seen_at=_to_utc(art.first_seen_at) if art.first_seen_at else None,
                label_created_at=effective_avail,
                provenance_status=art.provenance_status,
                gold_impact=lbl.gold_impact,
                driver=lbl.driver,
                is_price_report=bool(lbl.is_price_report),
                confidence=lbl.confidence,
                source=art.source,
                language=art.language,
                sentiment_version=lbl.sentiment_version,
                model_name=lbl.model_name,
                label_hash=lbl.label_hash or "",
            )
        )

    run_rows = db.execute(
        select(NewsCollectionRun).where(NewsCollectionRun.completed_at <= cutoff_utc)
    ).scalars().all()
    runs = [
        {
            "run_id": r.run_id,
            "started_at": _to_utc(r.started_at).isoformat(),
            "completed_at": _to_utc(r.completed_at).isoformat(),
            "status": r.status,
            "queries_attempted": r.queries_attempted,
            "queries_succeeded": r.queries_succeeded,
            "queries_failed": r.queries_failed,
        }
        for r in run_rows
    ]
    return records, runs


def load_stored_news_records_from_jsonl(
    audited_csv_path: Path,
    labels_jsonl_path: Path,
    collection_runs_path: Path | None = None,
) -> tuple[list[EligibleNewsRecord], list[dict[str, Any]]]:
    """
    Offline stored-label loader (for CSV+JSONL backtests): strictly joins `news_archive_audited.csv`
    against persisted `news_labels.jsonl` WITHOUT recomputing `evaluate_gold_impact`.
    """
    import csv

    labels_by_cluster: dict[str, list[dict[str, Any]]] = {}
    if labels_jsonl_path.exists():
        with labels_jsonl_path.open("r", encoding="utf-8") as lfh:
            for line in lfh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    cid = str(raw.get("story_cluster_id") or "")
                    if cid:
                        labels_by_cluster.setdefault(cid, []).append(raw)
                except Exception:
                    continue

    records: list[EligibleNewsRecord] = []
    if audited_csv_path.exists():
        with audited_csv_path.open("r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                status = (row.get("provenance_status") or "").strip()
                if status != ProvenanceStatus.VERIFIED_SOURCE.value:
                    continue
                pub_dt = parse_utc_iso(row.get("published_at"))
                first_seen_dt = parse_utc_iso(row.get("first_seen_at"))
                story_cid = (row.get("story_cluster_id") or "").strip()
                if pub_dt is None or first_seen_dt is None or not story_cid:
                    continue
                for lbl in labels_by_cluster.get(story_cid, []):
                    lbl_ts = parse_utc_iso(lbl.get("label_created_at"))
                    if lbl_ts is None:
                        continue
                    records.append(
                        EligibleNewsRecord(
                            story_cluster_id=story_cid,
                            title=row.get("title", ""),
                            published_at=pub_dt,
                            first_seen_at=first_seen_dt,
                            label_created_at=lbl_ts,
                            provenance_status=status,
                            gold_impact=str(lbl.get("gold_impact") or "UNKNOWN"),
                            driver=str(lbl.get("driver") or "UNKNOWN"),
                            is_price_report=bool(lbl.get("is_price_report", False)),
                            confidence=str(lbl.get("confidence") or "LOW"),
                            source=row.get("source", ""),
                            language=row.get("language", "en"),
                            sentiment_version=str(lbl.get("sentiment_version") or SENTIMENT_VERSION),
                            model_name=str(lbl.get("model_name") or ""),
                            label_hash=str(lbl.get("label_hash") or ""),
                        )
                    )

    runs: list[dict[str, Any]] = []
    if collection_runs_path and collection_runs_path.exists():
        with collection_runs_path.open("r", encoding="utf-8") as rfh:
            for line in rfh:
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(json.loads(line))
                except Exception:
                    continue

    return records, runs
