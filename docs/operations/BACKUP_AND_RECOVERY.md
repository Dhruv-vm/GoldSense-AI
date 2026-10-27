# Backup, Disaster Recovery & Data Durability

## 1. Data Preservation Philosophy
Precious metals financial data is irreplaceable. GoldSense AI employs a layered durability architecture:

1. **Git-Tracked Historical Data**:
   All raw CSV datasets under `data/` (`kjpl/kjpl_rates.csv`, `market/market_rates.csv`, `news/news_articles.csv`) are committed to version control on GitHub. Every historical tick has an immutable commit hash.
2. **PostgreSQL Point-in-Time Recovery**:
   For multi-user deployments, configure automated daily WAL archiving and snapshots on the managed database.
3. **Local SQLite Backup**:
   For local development or single-tenant deployments, `data/goldsense.db` can be archived simply by copying the file or running `.backup` in the SQLite CLI.

---

## 2. Recovery Procedure
If local state is corrupted:
```bash
# Revert working tree CSVs to clean git HEAD
git checkout HEAD -- data/

# Rebuild analyzed news cache from raw news CSV
cd backend && source .venv/bin/activate
python ml/training/sync_news_analysis.py

# Rebuild training feature matrix
python ml/features/build_training_dataset.py
```
