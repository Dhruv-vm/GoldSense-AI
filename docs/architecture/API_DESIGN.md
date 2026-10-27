# API Design & Endpoint Reference

All endpoints are hosted under `/api/v1` and return structured JSON responses.

---

## 1. Market & Bullion Endpoints

### `GET /api/v1/market/overview`
Returns the consolidated market view including physical spot (KJPL), global benchmarks (Yahoo Finance), mathematical parity in INR/g, domestic premium percentage, and real-time market session status.
```json
{
  "status": "SUCCESS",
  "kjpl": {
    "gold_mjdta": 14144.0,
    "silver_mjdta": 245.0,
    "change_24h_inr": 50.0,
    "freshness": "FRESH"
  },
  "market": {
    "xauusd": 5013.9,
    "xagusd": 84.82,
    "usdinr": 82.2,
    "freshness": "FRESH"
  },
  "derived": {
    "global_gold_inr_per_gram": 13250.71,
    "domestic_premium_inr_per_gram": 893.29,
    "domestic_premium_pct": 6.74,
    "global_gold_silver_ratio": 59.11
  },
  "trading_status": {
    "indian_physical_market": "OPEN",
    "global_futures_market": "OPEN",
    "server_time_ist": "2026-10-27 14:30:00 IST"
  },
  "overall_freshness": "FRESH"
}
```

### `POST /api/v1/market/refresh`
Triggers an on-demand market rate refresh. Subject to a 60-second debounce period.
- **Status 200**: Successfully checked and refreshed.
- **Status 429**: Rate limit exceeded (cooldown active).

---

## 2. Bullion Portfolio Endpoints

All portfolio requests identify the tenant user via server-side authorization dependency (`get_current_user`). When `AUTH_ENABLED=true`, a valid `Authorization: Bearer <token>` or `X-API-Key` is required.

### `GET /api/portfolio/summary`
Returns all holdings and summary valuation (total acquisition cost, current market value, unrealized PnL, fine gold/silver weights).

### `GET /api/portfolio/holdings`
Lists all active bullion holdings for the authenticated user.

### `GET /api/portfolio/history`
Returns a time-series array of historical portfolio valuations across recorded KJPL event dates.

### `POST /api/portfolio/holdings`
Creates a new physical holding. Supports weight in grams or kilograms, and handles optional/unknown acquisition costs.

### `PUT /api/portfolio/holdings/{holding_id}`
Updates an existing holding (weight, purity, quantity, acquisition cost, or notes).

### `DELETE /api/portfolio/{holding_id}`
Deletes a holding. Returns 404 if not found or if owned by another user.

---

## 3. Financial News Endpoints

### `GET /api/v1/news?limit=25`
Returns verified financial news articles with FinBERT sentiment labels (`POSITIVE`, `NEGATIVE`, `NEUTRAL`), confidence scores, and relevance tags.

---

## 4. Prediction Endpoints

### `GET /api/v1/prediction/latest`
Returns current model forecasting state and baseline persistence benchmarks. Emits honest low-data status:
```json
{
  "status": "EXPERIMENTAL_DATA_COLLECTION",
  "is_ready": false,
  "message": "Only 34 historical event observations collected. 50 minimum events required for production inference.",
  "metrics": {
    "current_samples": 34,
    "required_samples": 50,
    "progress_pct": 68.0
  },
  "baseline_benchmarks": {
    "naive_persistence": {
      "mae_inr_per_g": 68.28,
      "rmse_inr_per_g": 89.05
    },
    "sma_3_event": {
      "mae_inr_per_g": 135.89,
      "rmse_inr_per_g": 175.07
    }
  }
}
```
