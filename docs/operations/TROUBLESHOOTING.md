# Troubleshooting & Common Issues

## 1. Database Connection Refused
- **Symptom**: `OperationalError: could not connect to server: Connection refused`.
- **Cause**: PostgreSQL daemon is not running on localhost:5432.
- **Resolution**: GoldSense AI automatically detects this and falls back to SQLite (`data/goldsense.db`). To use PostgreSQL, ensure the PostgreSQL service is active (`brew services start postgresql` or `systemctl start postgresql`).

---

## 2. Refresh Cooldown (HTTP 429)
- **Symptom**: Refresh button returns status code 429.
- **Cause**: Debounce protection is active. Users may only request live rate fetches once every 60 seconds.
- **Resolution**: Wait until the countdown completes before requesting a fresh rate.

---

## 3. Empty News Feed or Stale Cache
- **Symptom**: New articles appear in `data/news/news_articles.csv` but do not show sentiment badges.
- **Cause**: Cache synchronization script has not run.
- **Resolution**: Run `python backend/ml/training/sync_news_analysis.py`.
