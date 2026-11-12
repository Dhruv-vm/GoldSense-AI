from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.provenance import ProvenanceStatus, parse_utc_iso

IMPACT_CLASSES = ("BULLISH", "BEARISH", "MIXED", "NEUTRAL", "UNKNOWN")

# Blinded annotator sheet (F-17): omits model pred_* columns to prevent anchoring bias.
BLIND_REVIEW_COLUMNS = [
    "sample_id",
    "published_at",
    "first_seen_at",
    "provenance_status",
    "source",
    "language",
    "story_cluster_id",
    "title",
    "url",
    "human_gold_impact",
    "human_driver",
    "human_is_price_report",
    "human_surprise",
    "reviewer_notes",
]

REFERENCE_COLUMNS = [
    "sample_id",
    "story_cluster_id",
    "pred_general_tone",
    "pred_gold_impact",
    "pred_driver",
    "pred_surprise",
    "pred_is_price_report",
    "pred_confidence",
    "pred_rationale",
    "stratum_weight",
]


def _has_existing_human_annotations(csv_path: Path) -> int:
    """Count rows in an existing review CSV that contain any manual annotation."""
    if not csv_path.exists():
        return 0
    annotated = 0
    with csv_path.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if any(
                (row.get(col) or "").strip()
                for col in (
                    "human_gold_impact",
                    "human_driver",
                    "human_is_price_report",
                    "human_surprise",
                    "reviewer_notes",
                )
            ):
                annotated += 1
    return annotated


def export_human_review_sample(
    audited_csv_path: Path,
    output_sample_path: Path,
    sample_size: int = 250,
    language_filter: str = "en",
    *,
    reference_output_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Create a deterministic stratified blind sample (~250 genuine non-fixture English headlines)
    for human annotation audit.

    F-13: Strictly refuses to overwrite `output_sample_path` if it contains any existing
    human annotations (raises FileExistsError even if `overwrite=True` when annotations exist).
    F-17: Balances sampling across time strata, sources, and predicted classes while keeping
    model predictions in a separate reference file (`reference_output_path`) to prevent
    annotator anchoring bias.
    """
    if not audited_csv_path.exists():
        raise FileNotFoundError(f"Audited news archive not found: {audited_csv_path}")

    existing_annotations = _has_existing_human_annotations(output_sample_path)
    if existing_annotations > 0:
        raise FileExistsError(
            f"Refusing to overwrite {output_sample_path}: contains {existing_annotations} existing "
            f"human-annotated row(s). Export aborted to preserve human annotations (F-13)."
        )
    if output_sample_path.exists() and not overwrite:
        raise FileExistsError(
            f"Review sample already exists at {output_sample_path}. Pass overwrite=True "
            f"(only allowed when zero human annotations are present) to regenerate."
        )

    candidates: list[dict[str, Any]] = []
    seen_clusters: set[str] = set()
    now = datetime.now(timezone.utc)

    with audited_csv_path.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            status = (row.get("provenance_status") or "").strip()
            if status in {
                ProvenanceStatus.SYNTHETIC_FIXTURE.value,
                ProvenanceStatus.DUPLICATE.value,
                ProvenanceStatus.INVALID.value,
            }:
                continue
            lang = (row.get("language") or "").strip().lower()
            if language_filter and lang != language_filter:
                continue
            cluster_id = (row.get("story_cluster_id") or "").strip()
            if cluster_id and cluster_id in seen_clusters:
                continue
            pub_dt = parse_utc_iso(row.get("published_at"))
            if pub_dt is None:
                continue
            if cluster_id:
                seen_clusters.add(cluster_id)

            impact = evaluate_gold_impact(
                title=row.get("title", ""),
                published_at=pub_dt,
                reference_time=now,
            )
            candidates.append(
                {
                    "published_at": pub_dt.isoformat(),
                    "week_bucket": pub_dt.strftime("%Y-W%W"),
                    "first_seen_at": row.get("first_seen_at", ""),
                    "provenance_status": status,
                    "source": row.get("source", ""),
                    "language": lang,
                    "story_cluster_id": cluster_id or impact["story_cluster_id"],
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "pred_general_tone": impact["general_tone"],
                    "pred_gold_impact": impact["gold_impact"],
                    "pred_driver": impact["driver"],
                    "pred_surprise": impact["surprise"],
                    "pred_is_price_report": str(impact["is_price_report"]),
                    "pred_confidence": impact["confidence"],
                    "pred_rationale": impact["evidence_rationale"],
                }
            )

    # Stratify deterministically across (pred_gold_impact, week_bucket) & diversify sources (F-17)
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        strata[(c["pred_gold_impact"], c["week_bucket"])].append(c)
    for items in strata.values():
        items.sort(key=lambda r: (r["published_at"], r["source"].lower(), r["story_cluster_id"]))

    target_n = min(sample_size, len(candidates))
    selected: list[dict[str, Any]] = []
    used_clusters: set[str] = set()
    source_cap = max(3, target_n // 15)
    source_counts: Counter[str] = Counter()

    strata_keys = sorted(strata.keys())
    cursor = {k: 0 for k in strata_keys}
    while len(selected) < target_n:
        progressed = False
        for k in strata_keys:
            if len(selected) >= target_n:
                break
            items = strata[k]
            while cursor[k] < len(items):
                cand = items[cursor[k]]
                cursor[k] += 1
                src_key = (cand["source"] or "unknown").strip().lower()
                if cand["story_cluster_id"] in used_clusters:
                    continue
                if source_counts[src_key] >= source_cap:
                    continue
                used_clusters.add(cand["story_cluster_id"])
                source_counts[src_key] += 1
                selected.append(cand)
                progressed = True
                break
        if not progressed:
            break

    # Relax source cap only if strictly needed to reach target_n
    if len(selected) < target_n:
        for cand in sorted(candidates, key=lambda r: (r["published_at"], r["story_cluster_id"])):
            if len(selected) >= target_n:
                break
            if cand["story_cluster_id"] not in used_clusters:
                used_clusters.add(cand["story_cluster_id"])
                selected.append(cand)

    selected.sort(key=lambda r: r["published_at"])
    output_sample_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path = reference_output_path or (output_sample_path.parent / "human_review_reference.csv")

    with output_sample_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BLIND_REVIEW_COLUMNS)
        writer.writeheader()
        for idx, item in enumerate(selected, start=1):
            writer.writerow(
                {
                    "sample_id": f"rev_{idx:04d}",
                    "published_at": item["published_at"],
                    "first_seen_at": item["first_seen_at"],
                    "provenance_status": item["provenance_status"],
                    "source": item["source"],
                    "language": item["language"],
                    "story_cluster_id": item["story_cluster_id"],
                    "title": item["title"],
                    "url": item["url"],
                    "human_gold_impact": "",
                    "human_driver": "",
                    "human_is_price_report": "",
                    "human_surprise": "",
                    "reviewer_notes": "",
                }
            )

    class_pop = Counter(c["pred_gold_impact"] for c in candidates)
    class_sample = Counter(item["pred_gold_impact"] for item in selected)

    with ref_path.open("w", encoding="utf-8", newline="") as rfh:
        rwriter = csv.DictWriter(rfh, fieldnames=REFERENCE_COLUMNS)
        rwriter.writeheader()
        for idx, item in enumerate(selected, start=1):
            cls_name = item["pred_gold_impact"]
            pop_share = class_pop[cls_name] / max(1, len(candidates))
            samp_share = class_sample[cls_name] / max(1, len(selected))
            weight = round(pop_share / samp_share, 6) if samp_share > 0 else 1.0
            rwriter.writerow(
                {
                    "sample_id": f"rev_{idx:04d}",
                    "story_cluster_id": item["story_cluster_id"],
                    "pred_general_tone": item["pred_general_tone"],
                    "pred_gold_impact": cls_name,
                    "pred_driver": item["pred_driver"],
                    "pred_surprise": item["pred_surprise"],
                    "pred_is_price_report": item["pred_is_price_report"],
                    "pred_confidence": item["pred_confidence"],
                    "pred_rationale": item["pred_rationale"],
                    "stratum_weight": f"{weight:.6f}",
                }
            )

    class_dist = Counter(item["pred_gold_impact"] for item in selected)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "output_path": str(output_sample_path),
        "reference_path": str(ref_path),
        "eligible_english_clusters": len(candidates),
        "exported_sample_count": len(selected),
        "distinct_sources_sampled": len(source_counts),
        "predicted_impact_distribution": dict(class_dist),
        "human_labeled_count": 0,
        "blinded_annotator_sheet": True,
    }


def evaluate_human_review_csv(
    review_csv_path: Path,
    min_reviewed: int = 20,
    reference_csv_path: Path | None = None,
) -> dict[str, Any]:
    """
    Evaluate predictions against human annotations. Supports blinded review CSVs paired
    with `human_review_reference.csv` as well as self-contained CSVs containing `pred_*`.
    """
    if not review_csv_path.exists():
        raise FileNotFoundError(f"Review CSV not found: {review_csv_path}")

    with review_csv_path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    ref_by_sample: dict[str, dict[str, str]] = {}
    ref_candidate = reference_csv_path or (review_csv_path.parent / "human_review_reference.csv")
    if ref_candidate.exists():
        with ref_candidate.open("r", encoding="utf-8") as rfh:
            for rrow in csv.DictReader(rfh):
                sid = (rrow.get("sample_id") or "").strip()
                if sid:
                    ref_by_sample[sid] = rrow

    labeled_pairs: list[tuple[str, str, float]] = []
    invalid_label_rows: list[dict[str, str]] = []
    price_report_tp = 0
    price_report_fp = 0
    price_report_fn = 0
    pred_unknown_total = 0

    for row in rows:
        sid = (row.get("sample_id") or "").strip()
        ref = ref_by_sample.get(sid, {})
        pred_impact = (row.get("pred_gold_impact") or ref.get("pred_gold_impact") or "UNKNOWN").strip().upper()
        if pred_impact not in IMPACT_CLASSES:
            pred_impact = "UNKNOWN"
        if pred_impact == "UNKNOWN":
            pred_unknown_total += 1

        raw_human = (row.get("human_gold_impact") or "").strip()
        if not raw_human:
            continue
        human_impact = raw_human.upper()
        if human_impact not in IMPACT_CLASSES:
            invalid_label_rows.append({"sample_id": sid, "invalid_value": raw_human})
            continue
        try:
            w = float(ref.get("stratum_weight") or 1.0)
        except Exception:
            w = 1.0
        labeled_pairs.append((human_impact, pred_impact, max(1e-6, w)))

        human_pr_raw = (row.get("human_is_price_report") or "").strip().lower()
        pred_pr_raw = str(row.get("pred_is_price_report") or ref.get("pred_is_price_report") or "").strip().lower()
        pred_pr = pred_pr_raw in {"true", "1"}
        if human_pr_raw in {"true", "false", "1", "0"}:
            human_pr = human_pr_raw in {"true", "1"}
            if pred_pr and human_pr:
                price_report_tp += 1
            elif pred_pr and not human_pr:
                price_report_fp += 1
            elif not pred_pr and human_pr:
                price_report_fn += 1

    n_total = len(rows)
    n_labeled = len(labeled_pairs)
    pred_unknown_rate = (pred_unknown_total / n_total) if n_total > 0 else 0.0

    if n_labeled < min_reviewed:
        return {
            "status": "PENDING_HUMAN_ANNOTATIONS",
            "total_sample_rows": n_total,
            "human_labeled_rows": n_labeled,
            "invalid_label_count": len(invalid_label_rows),
            "invalid_label_rows": invalid_label_rows[:25],
            "min_required_annotations": min_reviewed,
            "predicted_unknown_rate": round(pred_unknown_rate, 4),
            "message": (
                f"Human gold-impact evaluation requires at least {min_reviewed} valid manually annotated rows; "
                f"found {n_labeled} valid and {len(invalid_label_rows)} invalid. Populate `human_gold_impact` in {review_csv_path.name} and re-run."
            ),
        }

    confusion: dict[str, dict[str, int]] = {
        true_cls: {pred_cls: 0 for pred_cls in IMPACT_CLASSES}
        for true_cls in IMPACT_CLASSES
    }
    weighted_correct = 0.0
    total_weight = 0.0
    for true_cls, pred_cls, w in labeled_pairs:
        confusion[true_cls][pred_cls] += 1
        total_weight += w
        if true_cls == pred_cls:
            weighted_correct += w

    per_class_metrics: dict[str, dict[str, float | int]] = {}
    for cls in IMPACT_CLASSES:
        tp = confusion[cls][cls]
        fp = sum(confusion[other][cls] for other in IMPACT_CLASSES if other != cls)
        fn = sum(confusion[cls][other] for other in IMPACT_CLASSES if other != cls)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        support = tp + fn
        per_class_metrics[cls] = {
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    correct = sum(confusion[c][c] for c in IMPACT_CLASSES)
    accuracy = correct / n_labeled
    weighted_accuracy = weighted_correct / total_weight if total_weight > 0 else accuracy
    pe = sum(
        (sum(confusion[c].values()) / n_labeled)
        * (sum(confusion[r][c] for r in IMPACT_CLASSES) / n_labeled)
        for c in IMPACT_CLASSES
    )
    cohens_kappa = ((accuracy - pe) / (1.0 - pe)) if (1.0 - pe) > 1e-12 else 0.0
    pr_prec = price_report_tp / (price_report_tp + price_report_fp) if (price_report_tp + price_report_fp) > 0 else None

    return {
        "status": "EVALUATED" if not invalid_label_rows else "EVALUATED_WITH_INVALID_LABELS",
        "total_sample_rows": n_total,
        "human_labeled_rows": n_labeled,
        "invalid_label_count": len(invalid_label_rows),
        "invalid_label_rows": invalid_label_rows[:25],
        "accuracy": round(accuracy, 4),
        "sampling_weighted_accuracy": round(weighted_accuracy, 4),
        "cohens_kappa": round(cohens_kappa, 4),
        "predicted_unknown_rate": round(pred_unknown_rate, 4),
        "labeled_unknown_rate": round(
            sum(1 for _, pred, _ in labeled_pairs if pred == "UNKNOWN") / n_labeled,
            4,
        ),
        "price_report_precision": round(pr_prec, 4) if pr_prec is not None else None,
        "price_report_counts": {"tp": price_report_tp, "fp": price_report_fp, "fn": price_report_fn},
        "per_class_metrics": per_class_metrics,
        "confusion_matrix": confusion,
    }
