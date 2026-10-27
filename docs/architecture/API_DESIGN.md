# API Design & Endpoint Reference

All endpoints are hosted under `/api/v1` and return structured JSON responses.

---

## 1. Market & Bullion Endpoints

### `GET /api/v1/market/overview`
Returns the consolidated market view including physical spot (KJPL), global benchmarks (Yahoo Finance), mathematical parity in INR/g, and domestic premium percentage.
```json
{
  "status": "success",
  "data": {
    "kjpl_gold_inr_per_g": 14144.0,
    "kjpl_silver_inr_per_kg": 236248.0,
    "global_gold_usd_per_oz": 5013.9,
    "global_silver_usd_per_oz": 84.82,
    "usdinr": 82.2,
    "global_gold_inr_per_g": 13250.71,
    "domestic_premium_pct": 6.74,
    "last_updated": "2026-10-27T10:00:00Z",
    "freshness": "FRESH"
  }
}
```

### `POST /api/v1/market/refresh`
Triggers an on-demand market rate refresh. Subject to a 60-second debounce period.
- **Status 200**: Successfully checked and refreshed.
- **Status 429**: Rate limit exceeded (cooldown active).

---

## 2. Bullion Portfolio Endpoints

All portfolio requests identify the tenant user via the `X-User-ID` HTTP header (defaults to `default_user`).

### `GET /api/v1/portfolio`
Returns all holdings and summary valuation (total acquisition cost, current market value, unrealized PnL, fine gold/silver weights).

### `POST /api/v1/portfolio`
Creates a new physical holding.
**Request Body**:
```json
{
  "metal": "gold",
  "weight": 10.0,
  "unit": "g",
  "purity": 999.9,
  "purchase_price_per_g": 13800.0,
  "purchase_date": "2026-10-15T00:00:00Z",
  "notes": "10g Minted Bar"
}
```

### `DELETE /api/v1/portfolio/{holding_id}`
Deletes a holding. Returns 404 if not found or if owned by another user.

---

## 3. Financial News Endpoints

### `GET /api/v1/news?limit=20`
Returns verified financial news articles with FinBERT sentiment labels (`BULLISH`, `BEARISH`, `NEUTRAL`), confidence scores, and relevance tags.

---

## 4. Prediction Endpoints

### `GET /api/v1/prediction/latest`
Returns current model forecasting state. Emits honest low-data status:
```json
{
  "status": "EXPERIMENTAL_DATA_COLLECTION",
  "message": "Only 34 historical event observations collected. 50 minimum events required for production inference.",
  "sample_count": 34,
  "threshold": 50
}
```
