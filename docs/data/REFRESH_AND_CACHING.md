# Rate Refresh Lifecycle & Caching Strategy

## 1. Freshness Classification
To provide transparent visibility into market quote latency, `DataService` labels rates using three freshness tiers:

| Badge | Age Threshold | Significance |
| :--- | :--- | :--- |
| **`FRESH`** | $< 10\text{ minutes}$ | High-confidence real-time market quote. |
| **`DELAYED`** | $10\text{ to } 60\text{ minutes}$ | Standard intraday batch delay. |
| **`STALE`** | $> 60\text{ minutes}$ | Market closed, weekend, holiday, or upstream delay. |

---

## 2. Debounced Refresh Mechanism
When a user clicks "Refresh Rates" on the frontend terminal:
1. Client issues `POST /api/v1/market/refresh`.
2. Backend checks the in-memory timestamp of the last refresh request.
3. If less than 60 seconds have elapsed:
   - Responds with `HTTP 429 Too Many Requests`.
   - Returns JSON: `{"status": "cooldown", "remaining_seconds": N}`.
4. If 60+ seconds have elapsed:
   - Queries `yfinance` for live `GC=F`, `SI=F`, `USDINR=X`.
   - Appends new observation to `data/market/market_rates.csv`.
   - Updates memory cache and resets the 60-second timer.
   - Returns updated rates with status 200.
