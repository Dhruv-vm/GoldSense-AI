from __future__ import annotations

from pathlib import Path

import pandas as pd
import xgboost as xgb


DATASET_PATH = Path("ml/data/processed/gold_training_dataset.csv")
MODEL_DIR = Path("ml/models")

MIN_ROWS = 50

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


def main() -> None:
    print("[ML] Starting XGBoost training pipeline...")

    if not DATASET_PATH.exists():
        print(f"[ML] Dataset not found: {DATASET_PATH}")
        return

    df = pd.read_csv(DATASET_PATH)

    print(f"[ML] Dataset rows: {len(df)}")

    if len(df) < MIN_ROWS:
        print(
            f"[ML] Not enough data to train safely. "
            f"Need at least {MIN_ROWS} rows, got {len(df)}."
        )
        print("[ML] No model was created.")
        return

    missing = [column for column in FEATURE_COLUMNS if column not in df.columns]

    if missing:
        raise RuntimeError(f"Missing feature columns: {missing}")

    df = df.dropna(subset=FEATURE_COLUMNS + ["target_gold", "target_direction"])

    if len(df) < MIN_ROWS:
        print(
            f"[ML] Only {len(df)} complete rows remain after removing missing values."
        )
        print("[ML] No model was created.")
        return

    # Keep chronological order.
    df = df.sort_values("event_time").reset_index(drop=True)

    split_index = int(len(df) * 0.8)

    if split_index <= 0 or split_index >= len(df):
        raise RuntimeError("Invalid chronological train/validation split.")

    train_df = df.iloc[:split_index]
    validation_df = df.iloc[split_index:]

    X_train = train_df[FEATURE_COLUMNS]
    X_validation = validation_df[FEATURE_COLUMNS]

    y_train_price = train_df["target_gold"]
    y_validation_price = validation_df["target_gold"]

    direction_mapping = {"DOWN": 0, "FLAT": 1, "UP": 2}

    y_train_direction = train_df["target_direction"].map(direction_mapping)
    y_validation_direction = validation_df["target_direction"].map(direction_mapping)

    print(f"[ML] Training rows: {len(train_df)}")
    print(f"[ML] Validation rows: {len(validation_df)}")

    price_model = xgb.XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="reg:squarederror",
        random_state=42,
    )

    direction_model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=3,
        random_state=42,
    )

    print("[ML] Training price model...")
    price_model.fit(X_train, y_train_price)

    print("[ML] Training direction model...")
    direction_model.fit(X_train, y_train_direction)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    price_path = MODEL_DIR / "gold_price_xgb.json"
    direction_path = MODEL_DIR / "gold_direction_xgb.json"

    price_model.save_model(price_path)
    direction_model.save_model(direction_path)

    print(f"[ML] Saved price model: {price_path}")
    print(f"[ML] Saved direction model: {direction_path}")

    price_predictions = price_model.predict(X_validation)
    direction_predictions = direction_model.predict(X_validation)

    price_mae = abs(price_predictions - y_validation_price).mean()
    direction_accuracy = (
        direction_predictions == y_validation_direction.to_numpy()
    ).mean()

    print(f"[ML] Validation MAE: ₹{price_mae:.2f}")
    print(f"[ML] Validation direction accuracy: {direction_accuracy:.2%}")


if __name__ == "__main__":
    main()
