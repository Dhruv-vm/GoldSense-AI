from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def run_full_pipeline_update() -> dict:
    """
    Automated, end-to-end pipeline update:
    1. Clean KJPL events (kjpl_rates.csv -> kjpl_events.csv)
    2. Build market features (market_rates.csv -> market_features.csv)
    3. Synchronize FinBERT news analysis (news_articles.csv -> analyzed_news.csv)
    4. Rebuild zero-lookahead training dataset (gold_training_dataset.csv)
    5. Re-run walk-forward baseline benchmarks and data readiness evaluation.
    """
    start_time = datetime.now(timezone.utc)
    print("=" * 70)
    print(f"[PIPELINE UPDATE] Starting automated pipeline run at {start_time.isoformat()}...")
    print("=" * 70)

    stages = {}

    # Stage 1: Clean KJPL events
    try:
        from ml.training.clean_kjpl_events import main as clean_kjpl_main
        clean_kjpl_main()
        stages["kjpl_events"] = {"status": "SUCCESS"}
        print("[STAGE 1/5] KJPL events cleaned successfully.")
    except Exception as e:
        stages["kjpl_events"] = {"status": "ERROR", "error": str(e)}
        print(f"[STAGE 1/5 ERROR] {e}")

    # Stage 2: Market features
    try:
        from ml.training.market_features import main as market_main
        market_main()
        stages["market_features"] = {"status": "SUCCESS"}
        print("[STAGE 2/5] Market features built successfully.")
    except Exception as e:
        stages["market_features"] = {"status": "ERROR", "error": str(e)}
        print(f"[STAGE 2/5 ERROR] {e}")

    # Stage 3: Sync news cache
    try:
        from ml.training.sync_news_analysis import sync_analyzed_news
        news_synced = sync_analyzed_news()
        stages["news_sync"] = {"status": "SUCCESS", "new_articles_analyzed": news_synced}
        print(f"[STAGE 3/5] News cache synchronized: {news_synced} new articles scored.")
    except Exception as e:
        stages["news_sync"] = {"status": "ERROR", "error": str(e)}
        print(f"[STAGE 3/5 ERROR] {e}")

    # Stage 4: Build training dataset
    try:
        from ml.training.build_training_dataset import main as dataset_main
        dataset_main()
        stages["training_dataset"] = {"status": "SUCCESS"}
        print("[STAGE 4/5] Training dataset built successfully.")
    except Exception as e:
        stages["training_dataset"] = {"status": "ERROR", "error": str(e)}
        print(f"[STAGE 4/5 ERROR] {e}")

    # Stage 5: Walk-forward evaluation and data readiness
    try:
        from ml.training.walk_forward_evaluation import run_walk_forward_evaluation
        eval_report = run_walk_forward_evaluation()
        stages["evaluation"] = {"status": "SUCCESS", "report": eval_report}
        print(f"[STAGE 5/5] Walk-forward evaluation complete: status={eval_report.get('status')}")
    except Exception as e:
        stages["evaluation"] = {"status": "ERROR", "error": str(e)}
        print(f"[STAGE 5/5 ERROR] {e}")

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()
    print("=" * 70)
    print(f"[PIPELINE UPDATE] Completed in {duration:.2f} seconds.")
    print("=" * 70)

    return {
        "status": "SUCCESS",
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "stages": stages,
    }


if __name__ == "__main__":
    run_full_pipeline_update()
