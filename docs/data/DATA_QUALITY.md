# Data Quality, Anomaly Detection & Known Audit Findings

## 1. Audit Findings Across Datasets

### 1.1 KJPL Rates (`data/kjpl/kjpl_rates.csv`)
- **Row Count**: 41 raw observations.
- **Unique Events**: 35 unique dates after deduplication.
- **Range**: ₹13,060/g to ₹14,285/g for Gold 999; ₹185,000/kg to ₹245,000/kg for Silver 999.
- **Data Quality**: Verified clean. No null or negative rate values.

### 1.2 Market Rates (`data/market/market_rates.csv`)
- **Row Count**: 195 observations.
- **Collection Gap**: Scheduled workflow fires approximately every 4.5 hours.
- **Data Quality Finding**: Because collectors run every 4.5 hours, attempting to calculate 15-minute and 1-hour intraday returns produced 100% NaN values.
- **Corrective Action**: Intraday returns were removed from the ML feature matrix; only daily 1-day returns (`return_1d`) and domestic premiums are utilized.

### 1.3 News Articles (`data/news/news_articles.csv`)
- **Row Count**: 2,735 raw articles.
- **Seed Record Finding**: Rows 1–23 contained early synthetic or test seed URLs (returning HTTP 404/401).
- **Live Feed Rows**: Rows 24 to 2,735 are authentic live RSS articles from Reuters, CNBC, Bloomberg, and Economic Times.
- **Cache Synchronization**: Analyzed news cache was updated using `sync_news_analysis.py` to ensure all 2,735 articles are analyzed and sentiment-scored.

---

## 2. Invariants & Anomaly Rules
1. **Positive Price Invariant**: All rates must be strictly $> 0$.
2. **Premium Bound Invariant**: Domestic premium should reside within $[0\%, 15\%]$. A negative premium or premium $> 20\%$ triggers an anomaly warning.
3. **Date Monotonicity**: Timestamp sequences must progress forward in time.
