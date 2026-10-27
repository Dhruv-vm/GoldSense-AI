# Scheduled Jobs & Workflow Automation

## 1. Automated GitHub Actions Matrix

| Workflow | Path | Schedule | Purpose |
| :--- | :--- | :--- | :--- |
| **KJPL Rate Collector** | `.github/workflows/kjpl_collector.yml` | Twice daily (Morning & Evening IST) | Scrapes KJPL spot gold and silver rates. |
| **Market Data Collector**| `.github/workflows/market_collector.yml`| Every 4.5 hours | Ingests `GC=F`, `SI=F`, `USDINR=X` from Yahoo Finance. |
| **News RSS Collector** | `.github/workflows/news_collector.yml` | Every 6 hours | Fetches financial news feeds and tags bullion keywords. |

---

## 2. Maintenance & Sync Scripts

### News Sentiment Cache Sync
```bash
cd backend
source .venv/bin/activate
python ml/training/sync_news_analysis.py
```
Processes unprocessed articles through FinBERT and updates `analyzed_news.csv`.

### Training Matrix Rebuild
```bash
cd backend
source .venv/bin/activate
python ml/features/build_training_dataset.py
```
Re-aligns raw rates, market metrics, and news sentiment into `gold_training_dataset.csv`.
