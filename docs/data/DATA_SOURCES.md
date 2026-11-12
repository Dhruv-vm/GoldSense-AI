# Data Sources & Ingestion Inventory

VMD Bullion ingests **all bullion and FX rates exclusively from KJPL** (`docs/architecture/ADR_001_KJPL_ORACLE_NEON_VERCEL.md`), alongside GDELT/RSS financial news feeds for macro context.

---

## 1. Inventory Summary

| Data Source | Entity Monitored | Frequency | Primary Storage | Historical CSV / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **KJPL Pipeline A (MJDTA HTML)** | MJDTA Gold 24K (`INR/g`), MJDTA Silver (`INR/g`), LBMA AM/PM Fixes (`USD/oz`) | Twice daily IST (GitHub Actions) | Neon PostgreSQL (`bullion_rate_observations`) | `data/kjpl/kjpl_rates.csv` (`47` valid / `6` Oct-31 duplicates quarantined) |
| **KJPL Pipeline B (WS + `kjpl.txt`)** | 5-City Gold (`48`–`52`), `GOLD_1KG_9999` (`47`), `SPOT-GOLD`/`SPOT-SILVER`/`SPOT-INR`, Type 2 Contracts | Continuous (~1s live WS/`kjpl.txt`) | Neon PostgreSQL (`bullion_rate_observations`, `bullion_latest_rates`) | `data/kjpl/city_rates.csv` (`8` valid / `125` corrupt & duplicate rows quarantined) |
| **Yahoo Finance (`yfinance`)** | *Decommissioned (`GC=F`, `SI=F`, `USDINR=X`)* | Permanently disabled | None (historical `data/market/market_rates.csv` frozen for offline ML evaluation only) | Replaced exclusively by KJPL `SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR` |
| **Financial News (GDELT / RSS)** | Global & Indian macro news | 4x daily UTC (`03, 09, 15, 21`) | `data/news/live_news.csv` & `news_articles.csv` | Deduplicated & FinBERT-scored |

---

## 2. Source Details

### 2.1 KJPL (Live WebSocket, `kjpl.txt`, and MJDTA HTML)
- **Role**: Exclusive upstream source for Indian physical bullion hubs (`CHENNAI`, `BENGALURU`, `MUMBAI`, `COIMBATORE`, `HYDERABAD`), `GOLD_1KG_9999`, MJDTA benchmarks, LBMA fixes, and global spot USD + USD/INR feeds.
- **Full Field Contract**: See [KJPL Data Dictionary](KJPL_DATA_DICTIONARY.md) and [Remediation Report](REMEDIATION_REPORT.md).

### 2.2 Decommissioned External Sources
- **`yfinance` / Yahoo Finance**: Disabled in code (`backend/app/services/market/client.py`, `scripts/collect_market_csv.py`) and workflows (`.github/workflows/market-collector.yml`). No external spot or FX substitute APIs are permitted.

### 2.3 Financial News GDELT / RSS Feeds
- **Role**: Macroeconomic sentiment context for gold price movement.
- **Sources**: GDELT 2.0 & Financial RSS feeds (Reuters, CNBC, Economic Times, Financial Express).
- **Fields**: `article_id`, `title`, `source`, `url`, `published_at`, `collected_at`, `raw_text`, `is_gold_relevant`.
