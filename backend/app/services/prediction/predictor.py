from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from app.services.data_service import get_market_overview, PROJECT_ROOT
from app.services.prediction.forecast_engine import get_latest_mjdta_research_summary
from app.services.sentiment.live_signal import get_live_news_intelligence

MODEL_DIR = PROJECT_ROOT / "backend/ml/models"
PRICE_MODEL_PATH = MODEL_DIR / "gold_price_xgb.json"
DIRECTION_MODEL_PATH = MODEL_DIR / "gold_direction_xgb.json"
DATASET_PATH = PROJECT_ROOT / "backend/ml/data/processed/gold_training_dataset.csv"

MIN_REQUIRED_SAMPLES = 50

FEATURE_COLUMNS = [
    "usdinr",
    "xauusd",
    "xagusd",
    "usdinr_return_1d",
    "xauusd_return_1d",
    "xagusd_return_1d",
    "gold_global_inr_per_gram",
    "silver_global_inr_per_gram",
    "gold_silver_ratio",
    "kjpl_gold_change_pct",
    "kjpl_silver_change_pct",
    "kjpl_global_premium_pct",
    "kjpl_global_ratio",
]

DIRECTION_LABELS = {
    0: "DOWN",
    1: "FLAT",
    2: "UP",
}


def models_available() -> bool:
    return PRICE_MODEL_PATH.exists() and DIRECTION_MODEL_PATH.exists()


def get_prediction_status(db=None) -> dict:
    """
    Evaluates ML pipeline status, dataset readiness, and outputs active prediction
    if models are trained and validated, or honest low-data status if in collection phase.
    """
    sample_count = 0
    if DATASET_PATH.exists():
        try:
            df = pd.read_csv(DATASET_PATH)
            sample_count = len(df)
        except Exception:
            pass

    overview = get_market_overview()
    derived = overview.get("derived") or {}
    market = overview.get("market") or {}
    kjpl = overview.get("kjpl") or {}
    news_intel = get_live_news_intelligence(window_hours=24)

    # Load baseline benchmarks if available
    eval_report_path = PROJECT_ROOT / "backend/ml/data/processed/evaluation_report.json"
    baselines = {}
    if eval_report_path.exists():
        try:
            import json
            with eval_report_path.open("r", encoding="utf-8") as rf:
                rep_data = json.load(rf)
                baselines = rep_data.get("baseline_benchmarks", {})
        except Exception:
            pass

    if not models_available() or sample_count < MIN_REQUIRED_SAMPLES:
        shadow = get_mjdta_research_shadow_payload(db=db)
        return {
            "status": "EXPERIMENTAL_DATA_COLLECTION",
            "is_ready": False,
            "message": f"GoldSense AI enforces strict statistical integrity: supervised XGBoost time-series models require at least {MIN_REQUIRED_SAMPLES} daily market events to prevent overfitting. Currently collected: {sample_count} daily events ({MIN_REQUIRED_SAMPLES - sample_count} more needed).",
            "metrics": {
                "current_samples": sample_count,
                "required_samples": MIN_REQUIRED_SAMPLES,
                "progress_pct": round((sample_count / MIN_REQUIRED_SAMPLES) * 100, 1),
            },
            "baseline_benchmarks": baselines,
            "current_macro_snapshot": {
                "usdinr": market.get("usdinr"),
                "xauusd": market.get("xauusd"),
                "xagusd": market.get("xagusd"),
                "global_gold_inr_per_gram": derived.get("global_gold_inr_per_gram"),
                "domestic_premium_inr_per_gram": derived.get("domestic_premium_inr_per_gram"),
                "domestic_premium_pct": derived.get("domestic_premium_pct"),
                "latest_ground_truth_gold": kjpl.get("gold_mjdta"),
                "observation_time": overview.get("timestamp"),
            },
            "pipeline_specification": {
                "target_instrument": "KJPL MJDTA_GOLD_24K (EXCL_GST, 0.999 purity, INR / gram)",
                "forecast_horizon": "1 & 3 Valid Distinct MJDTA Publications Ahead",
                "validation_methodology": "Paired A/B/C/NO_CHANGE shadow walk-forward (`EXPERIMENT_PROTOCOL_V1`)",
                "system_isolation": "Strictly isolated from 5-city live terminal rates and external LBMA/yfinance feeds",
                "features_used": len(FEATURE_COLUMNS),
            },
            "news_intelligence": news_intel,
            "mjdta_shadow_research": shadow,
        }

    # If models are present, load and execute
    try:
        import xgboost as xgb

        price_model = xgb.XGBRegressor()
        price_model.load_model(str(PRICE_MODEL_PATH))

        direction_model = xgb.XGBClassifier()
        direction_model.load_model(str(DIRECTION_MODEL_PATH))

        feature_values = {
            "usdinr": market.get("usdinr", 95.0),
            "xauusd": market.get("xauusd", 4000.0),
            "xagusd": market.get("xagusd", 54.0),
            "usdinr_return_1d": market.get("usdinr_change_24h", 0.0),
            "xauusd_return_1d": market.get("xauusd_change_24h_pct", 0.0),
            "xagusd_return_1d": 0.0,
            "gold_global_inr_per_gram": derived.get("global_gold_inr_per_gram", 12300.0),
            "silver_global_inr_per_gram": derived.get("global_silver_inr_per_gram", 165.0),
            "gold_silver_ratio": derived.get("global_gold_silver_ratio", 74.0),
            "kjpl_gold_change_pct": kjpl.get("change_24h_pct", 0.0),
            "kjpl_silver_change_pct": 0.0,
            "kjpl_global_premium_pct": derived.get("domestic_premium_pct", 6.5),
            "kjpl_global_ratio": round(kjpl.get("gold_mjdta", 13100.0) / derived.get("global_gold_inr_per_gram", 12300.0), 4),
        }

        X = pd.DataFrame([[feature_values[col] for col in FEATURE_COLUMNS]], columns=FEATURE_COLUMNS)
        pred_price = float(price_model.predict(X)[0])
        pred_class = int(direction_model.predict(X)[0])
        pred_direction = DIRECTION_LABELS.get(pred_class, "UNKNOWN")

        current_price = kjpl.get("gold_mjdta", pred_price)
        expected_change = round(pred_price - current_price, 2)
        expected_change_pct = round((expected_change / current_price) * 100, 2)

        return {
            "status": "SUCCESS",
            "is_ready": True,
            "predicted_gold_price": round(pred_price, 2),
            "predicted_direction": pred_direction,
            "expected_change_inr": expected_change,
            "expected_change_pct": expected_change_pct,
            "forecast_horizon": "1 Trading Day",
            "model_version": "xgboost-v1",
            "predicted_at": datetime.now(timezone.utc).isoformat(),
            "news_intelligence": news_intel,
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "is_ready": False,
            "message": f"Inference execution failed: {str(e)}",
        }


def get_mjdta_research_shadow_payload(db=None) -> dict:
    """Return compact DB-backed MJDTA shadow & backtest summary."""
    from app.db.session import ENVIRONMENT, is_postgres_configured
    from app.services.data_service import init_database

    # NEW-8: When non-production SQLite test clients hit routes without entering FastAPI lifespan,
    # ensure tables exist on a fresh clean DB; PostgreSQL/production always relies on Alembic.
    if ENVIRONMENT != "production" and not is_postgres_configured():
        init_database()

    res = get_latest_mjdta_research_summary(db=db, repo_root=PROJECT_ROOT)
    return {
        k: v
        for k, v in res.items()
        if k not in ("snapshots", "forecasts", "evaluations")
    }


def predict(db=None) -> dict:
    return get_prediction_status(db=db)
