# Market Data Pipeline & Scheduled Workflows

## 1. Automated GitHub Actions Ingestion
Market and bullion data are collected on cron schedules via GitHub Actions workflows:

1. **KJPL Scraper Workflow (`.github/workflows/kjpl_collector.yml`)**:
   - Runs on schedule during Indian market operating hours.
   - Extracts current physical spot rates from KJPL.
   - Appends deduplicated rows to `data/kjpl/kjpl_rates.csv` and commits to `develop`.

2. **Market Collector Workflow (`.github/workflows/market_collector.yml`)**:
   - Queries `yfinance` for `GC=F`, `SI=F`, and `USDINR=X`.
   - Computes estimated parity rates.
   - Appends observations to `data/market/market_rates.csv`.

3. **News Collector Workflow (`.github/workflows/news_collector.yml`)**:
   - Ingests RSS feeds, applies keyword filtering for bullion topics, and persists raw articles to `data/news/news_articles.csv`.

---

## 2. Ingestion Resilience & Schema Integrity
- **Deduplication**: Ingestion jobs key on timestamp and title hashes to avoid duplicate rows.
- **Append-Only Policy**: No collector job is permitted to overwrite or rewrite historical CSV records.
- **Fail-Safe Execution**: If an external endpoint times out or is blocked, the job logs a warning and exits cleanly without polluting the persistent CSV files.
