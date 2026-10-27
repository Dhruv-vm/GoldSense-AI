# Data Sources & Ingestion Inventory

GoldSense AI ingests data from three core external sources into flat, append-only CSV datasets.

---

## 1. Inventory Summary

| Data Source | Entity Monitored | Frequency | Storage Location | Record Count |
| :--- | :--- | :--- | :--- | :--- |
| **KJPL Bullion** | Gold 999 (INR/g), Silver 999 (INR/kg) | Daily (~market open/close) | `data/kjpl/kjpl_rates.csv` | 41 raw observations (35 unique trading events) |
| **Yahoo Finance** | COMEX Gold (`GC=F`), Silver (`SI=F`), `USDINR=X` | Scheduled (every ~4.5h) | `data/market/market_rates.csv` | 195 observations |
| **Financial News RSS** | Global & Indian financial news desks | Scheduled (daily) | `data/news/news_articles.csv` | 2,735 raw articles |

---

## 2. Source Details

### 2.1 KJPL (Kundanmal Jewellers Pvt. Ltd., Ahmedabad)
- **Role**: Primary ground-truth physical delivery benchmark for wholesale bullion in Western India.
- **Scraper**: Automated scraping workflow capturing spot opening and closing rates.
- **Fields**: `timestamp`, `gold_rate_inr_per_g`, `silver_rate_inr_per_kg`.

### 2.2 Yahoo Finance (`yfinance`)
- **Role**: Global spot and futures market benchmarks.
- **Tickers**:
  - `GC=F`: COMEX Gold Futures (USD per troy ounce).
  - `SI=F`: COMEX Silver Futures (USD per troy ounce).
  - `USDINR=X`: USD to INR exchange rate.
- **Fields**: `timestamp`, `gold_usd`, `silver_usd`, `usdinr`, `gold_inr_est`, `silver_inr_est`.

### 2.3 Financial News RSS Feeds
- **Role**: Macroeconomic sentiment context for gold price movement.
- **Sources**: Reuters, Bloomberg, CNBC, Economic Times, Financial Express.
- **Fields**: `article_id`, `title`, `source`, `url`, `published_at`, `collected_at`, `raw_text`, `is_gold_relevant`.
