from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.prediction.forecast_engine import get_latest_mjdta_research_summary
from app.services.sentiment.human_review import evaluate_human_review_csv
from app.services.sentiment.provenance import ProvenanceStatus


def generate_daily_research_report(
    repo_root: Path,
    *,
    db: Session | None = None,
    md_output_path: Path | None = None,
    json_output_path: Path | None = None,
) -> dict[str, Any]:
    """
    Build reproducible daily MJDTA operations & shadow research report from
    the authoritative DB-backed MJDTA ledger, separating PROSPECTIVE from BACKTEST.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    audited_news_csv = repo_root / "data/news/news_archive_audited.csv"
    runs_jsonl = repo_root / "data/news/collection_runs.jsonl"
    review_csv = repo_root / "data/news/human_review_sample.csv"
    review_ref = repo_root / "data/news/human_review_reference.csv"

    provenance_counts: Counter[str] = Counter()
    lang_counts: Counter[str] = Counter()
    if audited_news_csv.exists():
        with audited_news_csv.open("r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                provenance_counts[row.get("provenance_status", "UNKNOWN")] += 1
                if row.get("provenance_status") in {
                    ProvenanceStatus.VERIFIED_SOURCE.value,
                    ProvenanceStatus.HISTORICAL_UNVERIFIED_AVAILABILITY.value,
                }:
                    lang_counts[row.get("language", "unknown")] += 1

    runs: list[dict[str, Any]] = []
    if runs_jsonl.exists():
        with runs_jsonl.open("r", encoding="utf-8") as rf:
            for line in rf:
                line = line.strip()
                if line:
                    try:
                        runs.append(json.loads(line))
                    except Exception:
                        continue

    human_eval = (
        evaluate_human_review_csv(review_csv, reference_csv_path=review_ref)
        if review_csv.exists()
        else {"status": "NOT_EXPORTED", "human_labeled_rows": 0}
    )

    research = get_latest_mjdta_research_summary(db=db, repo_root=repo_root)
    payload = {
        "generated_at": generated_at,
        "protocol_version": research.get("protocol_version"),
        "model_version": research.get("model_version"),
        "status": research.get("status"),
        "backtest_status": research.get("backtest_status"),
        "target_spec": research.get("target_spec"),
        "mjdta_audit": research.get("mjdta_audit", {}),
        "news_archive_provenance": dict(provenance_counts),
        "news_languages_top5": dict(lang_counts.most_common(5)),
        "collector_v2_runs_count": len(runs),
        "latest_collector_v2_run": runs[-1] if runs else None,
        "human_review": human_eval,
        "eligible_publications": research.get("eligible_publications", 0),
        "verified_news_coverage_origins": research.get("verified_news_coverage_origins", 0),
        "min_evaluation_samples": research.get("min_evaluation_samples", 30),
        "prospective_ledger": research.get("prospective_ledger", {}),
        "latest_snapshot": research.get("latest_snapshot"),
        "latest_forecasts": research.get("latest_forecasts", []),
        "metrics_by_horizon": research.get("metrics_by_horizon", {}),
    }

    if json_output_path is not None:
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        json_output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if md_output_path is not None:
        md_output_path.parent.mkdir(parents=True, exist_ok=True)
        mjdta_audit = payload["mjdta_audit"]
        prosp = payload["prospective_ledger"] or {}
        latest_snap = payload["latest_snapshot"] or {}

        net_imp_disp = (
            f"{latest_snap['net_impact']:+.4f}"
            if latest_snap.get("net_impact") is not None
            else "UNAVAILABLE"
        )
        unk_disp = (
            f"{latest_snap['unknown_share']:.4f}"
            if latest_snap.get("unknown_share") is not None
            else "UNAVAILABLE"
        )

        lines = [
            "# VMD Bullion — Daily Operations & MJDTA Research Report",
            "",
            f"- **Generated at (UTC):** `{generated_at}`",
            f"- **Protocol / Model:** `{payload['protocol_version']}` / `{payload['model_version']}`",
            f"- **Prospective Shadow Ledger Status:** `{payload['status']}` (Origins logged: `{prosp.get('total_prospective_origins', 0)}`, Matured: `{prosp.get('matured_prospective_origins', 0)}` / `{payload['min_evaluation_samples']}` required)",
            f"- **Backtest Study Status:** `{payload['backtest_status']}`",
            f"- **Target Instrument:** `MJDTA_GOLD_24K` (`EXCL_GST`, Purity `0.999`, `INR/1g`) from DB `{mjdta_audit.get('source_backend', 'database')}`",
            "",
            "## 1. MJDTA DB Series & Collector Health",
            "",
            f"- DB MJDTA total valid rows inspected: `{mjdta_audit.get('total_raw_rows', 0)}`",
            f"- Eligible distinct MJDTA publications: `{mjdta_audit.get('eligible_publications', 0)}`",
            f"- Excluded weekend/uncertain rows: `{mjdta_audit.get('excluded_observations', 0)}` (`{mjdta_audit.get('status_counts', {})}`)",
            f"- Verified news coverage origins in backtest window: `{payload['verified_news_coverage_origins']}`",
            f"- Human review audit (`human_review_sample.csv`): `{human_eval.get('status')}` (`{human_eval.get('human_labeled_rows', 0)}` / `{human_eval.get('total_sample_rows', 0)}` labeled)",
            "",
            "## 2. News Archive Provenance Summary",
            "",
            "| Provenance Status | Count |",
            "|---|---:|",
        ]
        for k, v in provenance_counts.items():
            lines.append(f"| `{k}` | {v} |")

        lines.extend(
            [
                "",
                "## 3. Latest Cutoff Snapshot & Frontier Arm Outputs",
                "",
                f"- **Origin Observed At (UTC):** `{latest_snap.get('origin_observed_at', 'N/A')}`",
                f"- **Origin MJDTA 24K Gold (`INR/g`):** `{latest_snap.get('origin_gold_price_inr_per_g', 'N/A')}`",
                f"- **News Cutoff Features:** `n_clusters_relevant={latest_snap.get('n_clusters_relevant', 0)}`, `net_impact={net_imp_disp}`, `unknown_share={unk_disp}`, `coverage_ok={latest_snap.get('coverage_ok', False)}`",
                "",
                "| Mode | Horizon | Arm | Pred Log Return | Pred Price (INR/g) | Direction | P(Up) | Status |",
                "|---|---:|---|---:|---:|---|---:|---|",
            ]
        )
        for fc in payload["latest_forecasts"]:
            plr = f"{fc['predicted_log_return']:+.6f}" if fc.get("predicted_log_return") is not None else "N/A"
            ppr = f"{fc['predicted_price_inr_per_g']:.2f}" if fc.get("predicted_price_inr_per_g") is not None else "N/A"
            pup = f"{fc['up_probability']:.4f}" if fc.get("up_probability") is not None else "N/A"
            lines.append(
                f"| `{fc.get('generation_mode', 'BACKTEST')}` | `h={fc['horizon_publications']}` | `{fc['arm']}` | `{plr}` | `{ppr}` | `{fc['predicted_direction']}` | `{pup}` | `{fc['status']}` |"
            )

        lines.extend(
            [
                "",
                "## 4. Comparable-Origin Evaluation (`BACKTEST` Diagnostic Study)",
                "",
            ]
        )
        for h_key, h_block in payload["metrics_by_horizon"].items():
            lines.append(
                f"### Horizon `{h_key}` (Paired 4-Arm Comparable Origins: `{h_block.get('paired_comparable_count', 0)}`)"
            )
            lines.append("")
            lines.append("| Arm | Bucket | Samples | Status | MAE (INR/g) | RMSE (INR/g) | Dir Acc | Brier |")
            lines.append("|---|---|---:|---|---:|---:|---:|---:|")
            for arm, splits in h_block.get("arms", {}).items():
                for split_name in ("paired_comparable_origins", "all_valid_origins", "non_overlapping_paired"):
                    m = splits[split_name]
                    mae_inr = f"{m['mae_inr_per_g']:.2f}" if m["mae_inr_per_g"] is not None else "N/A"
                    rmse_inr = f"{m['rmse_inr_per_g']:.2f}" if m["rmse_inr_per_g"] is not None else "N/A"
                    dacc = f"{m['directional_accuracy']:.4f}" if m["directional_accuracy"] is not None else "N/A"
                    brier = f"{m['brier_score']:.4f}" if m["brier_score"] is not None else "N/A"
                    lines.append(
                        f"| `{arm}` | `{split_name}` | {m['sample_count']} | `{m['status']}` | {mae_inr} | {rmse_inr} | {dacc} | {brier} |"
                    )
            dm = h_block.get("diebold_mariano", {})
            lines.append("")
            lines.append(f"- DM (`HYBRID vs PRICE_ONLY`, HLN Student-t): `{dm.get('hybrid_vs_price_only')}`")
            lines.append(f"- DM (`HYBRID vs NO_CHANGE`, HLN Student-t): `{dm.get('hybrid_vs_no_change')}`")
            lines.append("")

        md_output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return payload
