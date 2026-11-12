# Market Data Pipeline & Scheduled Workflows (ADR-001)

## 1. Active KJPL-Exclusive Ingestion Pipelines

1. **Pipeline A — KJPL MJDTA Collector (`.github/workflows/kjpl-collector.yml`)**:
   - Runs twice-daily IST crons via GitHub Actions writing directly into Neon PostgreSQL (`NEON_DATABASE_URL`, `DB_USE_NULLPOOL=true`, `ENABLE_CSV_MIRROR=false`).
   - Strictly executes `--mjdta-only` (MJDTA Gold/Silver + LBMA USD fixes under `KJPL_MJDTA_COLLECTOR`). An explicit interim `--snapshot-only` step (`KJPL_SNAPSHOT_COLLECTOR`) runs independently while `vars.ORACLE_WORKER_ACTIVE != 'true'`, without automated commits to `develop`.

2. **Pipeline B — KJPL Live Terminal Worker (`scripts/kjpl_live_worker.py`)**:
   - Runs continuously on Oracle Cloud Always Free (`deploy/oracle/vmd-kjpl-worker.service`) under an `fcntl` single-writer lock.
   - Consumes `ws://www.kjpl.in/ws` and `http://www.kjpl.in/client/kjpl.txt` (`SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR`, Type 2 Indian contracts, 5-city 100g 999 gold, and `GOLD_1KG_9999`) directly into Neon PostgreSQL.

3. **Decommissioned Market Collector (`.github/workflows/market-collector.yml`)**:
   - Yahoo Finance (`yfinance`) collection is permanently decommissioned per ADR-001. Global spot and FX parity come strictly from KJPL.

4. **News Collector Workflow (`.github/workflows/news-collector.yml`)**:
   - Ingests GDELT 2.0 / financial RSS feeds into `data/news/live_news.csv` and `data/news/news_articles.csv`.

---

## 2. Ingestion Resilience & Schema Integrity
- **Validation & Quarantine**: Observations failing product/unit sanity bounds (`backend/app/services/kjpl/validator.py`) are quarantined (`QUARANTINED`) rather than contaminating clean series.
- **Unchanged Rate Suppression**: Repeated identical prices increment `last_verified_at` on `bullion_latest_rates` and log `is_changed=False` cleanly.
- **Fail-Safe Execution**: If upstream KJPL endpoints are unavailable, collector outages are logged in `collector_runs` / `data_source_status` without inventing prices.
