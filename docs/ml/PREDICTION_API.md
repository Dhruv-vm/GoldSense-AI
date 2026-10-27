# Prediction API & Serving Pipeline

## 1. Endpoint Contract: `GET /api/v1/prediction/latest`

The prediction endpoint serves real-time forward forecasts or transparent status messages based on data sufficiency.

### Case A: Experimental Collection Phase ($N < 50$ events)
When historical rows are fewer than 50 samples:
```json
{
  "status": "EXPERIMENTAL_DATA_COLLECTION",
  "message": "Only 34 historical event observations collected. 50 minimum events required for production inference.",
  "sample_count": 34,
  "threshold": 50,
  "confidence": "LOW",
  "recommendation": "Maintain daily ingestion to accumulate 16 additional trading sessions."
}
```

### Case B: Production Forecast ($N \ge 50$ events)
```json
{
  "status": "PRODUCTION_FORECAST",
  "predicted_next_event_gold": 14195.5,
  "current_rate": 14144.0,
  "predicted_delta_inr": 51.5,
  "predicted_direction": "UP",
  "confidence_interval_95": [14080.0, 14310.0],
  "feature_importance": {
    "gold_global_inr_per_gram": 0.42,
    "usdinr_return_1d": 0.28,
    "sentiment_score_mean": 0.18,
    "xauusd_return_1d": 0.12
  }
}
```
