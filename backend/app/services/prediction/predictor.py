from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import xgboost as xgb

from app.services.data_service import get_market_overview, PROJECT_ROOT

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


def get_prediction_status() -> dict:
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
    derived = overview.get("derived", {})
    market = overview.get("market", {})
    kjpl = overview.get("kjpl", {})

    if not models_available() or sample_count < MIN_REQUIRED_SAMPLES:
        return {
            "status": "EXPERIMENTAL_DATA_COLLECTION",
            "is_ready": False,
            "message": f"GoldSense AI enforces strict statistical integrity: supervised XGBoost time-series models require at least {MIN_REQUIRED_SAMPLES} daily market events to prevent overfitting. Currently collected: {sample_count} daily events ({MIN_REQUIRED_SAMPLES - sample_count} more needed).",
            "metrics": {
                "current_samples": sample_count,
                "required_samples": MIN_REQUIRED_SAMPLES,
                "progress_pct": round((sample_count / MIN_REQUIRED_SAMPLES) * 100, 1),
            },
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
                "target_instrument": "KJPL MJDTA 24K Pure Gold (INR / gram)",
                "forecast_horizon": "1 Trading Day (Next Published Rate)",
                "validation_methodology": "Walk-forward chronological holdout (strictly no-lookahead)",
                "features_used": len(FEATURE_COLUMNS),
            },
        }

    # If models are present, load and execute
    try:
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
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "is_ready": False,
            "message": f"Inference execution failed: {str(e)}",
        }


def predict() -> dict:
    return get_prediction_status()
