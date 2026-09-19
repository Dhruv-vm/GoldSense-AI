from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import xgboost as xgb
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.feature_snapshot import FeatureSnapshot
from app.models.prediction import Prediction


MODEL_DIR = Path("ml/models")
PRICE_MODEL_PATH = MODEL_DIR / "gold_price_xgb.json"
DIRECTION_MODEL_PATH = MODEL_DIR / "gold_direction_xgb.json"

FEATURE_COLUMNS = [
    "usdinr",
    "xauusd",
    "xagusd",
    "gold_return_15m",
    "xau_return_15m",
    "xagusd_return_15m",
    "usdinr_return_15m",
    "gold_return_1h",
    "xau_return_1h",
    "xagusd_return_1h",
    "usdinr_return_1h",
    "gold_return_4h",
    "xau_return_4h",
    "xagusd_return_4h",
    "usdinr_return_4h",
    "gold_return_1d",
    "xau_return_1d",
    "xagusd_return_1d",
    "usdinr_return_1d",
    "gold_xau_inr_estimate",
    "kjpl_global_premium_pct",
    "gold_xau_ratio",
]

DIRECTION_LABELS = {
    0: "DOWN",
    1: "FLAT",
    2: "UP",
}


def models_available() -> bool:
    return PRICE_MODEL_PATH.exists() and DIRECTION_MODEL_PATH.exists()


def get_latest_snapshot() -> FeatureSnapshot | None:
    with SessionLocal() as session:
        statement = (
            select(FeatureSnapshot)
            .order_by(FeatureSnapshot.observed_at.desc())
            .limit(1)
        )
        return session.scalar(statement)


def snapshot_to_features(snapshot: FeatureSnapshot) -> pd.DataFrame:
    """
    Convert the latest feature snapshot into the exact feature schema
    expected by the trained XGBoost models.
    """

    values = {
        "usdinr": snapshot.usdinr,
        "xauusd": snapshot.xauusd,
        "xagusd": snapshot.xagusd,
        "gold_return_15m": 0.0,
        "xau_return_15m": 0.0,
        "xagusd_return_15m": 0.0,
        "usdinr_return_15m": 0.0,
        "gold_return_1h": 0.0,
        "xau_return_1h": 0.0,
        "xagusd_return_1h": 0.0,
        "usdinr_return_1h": 0.0,
        "gold_return_4h": 0.0,
        "xau_return_4h": 0.0,
        "xagusd_return_4h": 0.0,
        "usdinr_return_4h": 0.0,
        "gold_return_1d": 0.0,
        "xau_return_1d": 0.0,
        "xagusd_return_1d": 0.0,
        "usdinr_return_1d": 0.0,
        "gold_xau_inr_estimate": (
            snapshot.xauusd * snapshot.usdinr / 31.1034768
        ),
        "kjpl_global_premium_pct": (
            (
                snapshot.kjpl_gold
                - (snapshot.xauusd * snapshot.usdinr / 31.1034768)
            )
            / (snapshot.xauusd * snapshot.usdinr / 31.1034768)
            * 100
        ),
        "gold_xau_ratio": (
            snapshot.kjpl_gold
            / (snapshot.xauusd * snapshot.usdinr / 31.1034768)
        ),
    }

    return pd.DataFrame([[values[column] for column in FEATURE_COLUMNS]], columns=FEATURE_COLUMNS)


def predict() -> dict:
    if not models_available():
        return {
            "status": "MODEL_NOT_READY",
            "message": "No trained XGBoost model is available yet.",
        }

    snapshot = get_latest_snapshot()

    if snapshot is None:
        return {
            "status": "NO_FEATURE_SNAPSHOT",
            "message": "No feature snapshot is available.",
        }

    features = snapshot_to_features(snapshot)

    price_model = xgb.XGBRegressor()
    price_model.load_model(PRICE_MODEL_PATH)

    direction_model = xgb.XGBClassifier()
    direction_model.load_model(DIRECTION_MODEL_PATH)

    predicted_price = float(price_model.predict(features)[0])
    direction_class = int(direction_model.predict(features)[0])
    predicted_direction = DIRECTION_LABELS.get(direction_class, "UNKNOWN")

    prediction = Prediction(
        predicted_at=datetime.now(snapshot.observed_at.tzinfo),
        target_time=None,
        predicted_gold_price=predicted_price,
        predicted_direction=predicted_direction,
        model_version="xgboost-v1",
    )

    with SessionLocal() as session:
        session.add(prediction)
        session.commit()
        session.refresh(prediction)

        prediction_id = prediction.id

    return {
        "status": "SUCCESS",
        "prediction_id": prediction_id,
        "predicted_gold_price": predicted_price,
        "predicted_direction": predicted_direction,
        "model_version": "xgboost-v1",
        "feature_snapshot_id": snapshot.id,
        "predicted_at": prediction.predicted_at.isoformat(),
    }
