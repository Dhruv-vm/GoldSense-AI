# Data Leakage Prevention & Audit Checkpoints

## 1. Principles of Financial Data Leakage
Data leakage in financial time series causes artificially inflated backtest performance that fails in live markets. GoldSense AI enforces four technical guards against leakage:

1. **Strict Temporal Ordering**:
   Features $X_t$ are paired strictly with $y_{t+1}$. Under no circumstances can feature computation reference price at or after $t+1$.
2. **News Publication Cutoff**:
   News queries filter explicitly by `published_at <= event_timestamp`. Articles published even one minute after $T_{event}$ are rejected from window aggregation for that event.
3. **Scaler & Preprocessor Fit**:
   Standardization scalers (e.g. `StandardScaler`) are fit exclusively on the training folds and applied to test folds without recomputing means or standard deviations across the entire dataset.
4. **Independent Test Partitioning**:
   The walk-forward evaluation leaves a test buffer between training windows to account for intraday execution settlement.
