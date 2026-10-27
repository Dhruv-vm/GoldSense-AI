# Machine Learning Architecture

## 1. Objective & Formulation
The prediction engine forecasts the price level and direction of the next KJPL physical gold rate event ($T_{t+1}$) given market state, domestic premium, and news sentiment at event $T_t$.

$$\hat{y}_{t+1} = f(X_t; \Theta)$$

Where:
- $X_t$: Feature vector observed at or prior to $T_t$.
- $y_{t+1}$: The actual gold rate at the next trading event $T_{t+1}$ (`next_event_gold`).
- $f$: Supervised learning regressor (Random Forest Regressor / Gradient Boosting).

---

## 2. ML System Diagram

```mermaid
flowchart TD
    KJPL[data/kjpl/kjpl_rates.csv] --> Align[Zero-Lookahead Alignment]
    Market[data/market/market_rates.csv] --> Align
    News[ml/data/processed/analyzed_news.csv] --> Align
    Align --> Dataset[ml/data/processed/gold_training_dataset.csv]
    
    Dataset --> Gatekeeper{Sample Count Check}
    Gatekeeper -- "N < 50" --> ExpMode["EXPERIMENTAL_DATA_COLLECTION Status (Transparent UI Warning)"]
    Gatekeeper -- "N >= 50" --> Train[train_model.py]
    
    Train --> Eval[Time-Series Split Walk-Forward Validation]
    Eval --> Artifact[ml/models/gold_price_model.joblib]
    Artifact --> PredAPI[Prediction API /api/v1/prediction/latest]
```
