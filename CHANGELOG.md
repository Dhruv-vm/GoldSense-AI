# CHANGELOG

All notable changes to the **GoldSense AI** platform are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0-develop] - 2026-10-27

### Added
- **Personal Bullion Portfolio Tracker**:
  - SQLAlchemy model `PortfolioHolding` with metal type, gross weight, fine weight, purity, acquisition cost, and tenant `user_id`.
  - Comprehensive `PortfolioService` with gram/kilogram conversion, 999.9/995/916/750 purity math, and real-time market mark-to-market valuation.
  - REST endpoints at `/api/portfolio` supporting full CRUD (Add, Edit, List, Delete) and historical valuation trajectory (`/history`).
  - Safe handling of unknown or inherited acquisition costs without distorting unrealized PnL.
  - Interactive portfolio dashboard in frontend terminal with Edit modal, asset breakdown cards, and historical trajectory table.
- **Server-Side Authorization & Tenancy**:
  - `app.core.auth.get_current_user` enforcing Bearer token and X-API-Key verification when `AUTH_ENABLED=true`.
  - Prevents caller-supplied user ID bypass and protects multi-tenant isolation.
- **Automated Pipeline & Walk-Forward Evaluation**:
  - End-to-end pipeline runner `update_pipeline.py` executing cleaning, market feature building, news sync, dataset rebuild, and evaluation in sequence.
  - Walk-forward baseline evaluation script `walk_forward_evaluation.py` establishing persistence benchmarks (MAE: ₹68.28/g, RMSE: ₹89.05/g).
  - Trading session status monitor (`get_market_trading_status()`) identifying open, after-hours, and weekend-closed states.
- **Frontend Dashboard Terminal**:
  - Enhanced to institutional 8-tab terminal (Overview, Markets, My Bullion, Predictions, News Feed, Research & History, Alerts, Settings).
  - Next.js 16 (Turbopack) build verified with zero errors.
- **Test Suite Expansion**:
  - Expanded backend test suite from 59 to **66 passing pytest tests (100% pass rate)**.
- **Unified Market Data Service**:
  - `DataService` in `backend/app/services/data_service.py` with CSV fallback, metric conversions (Troy oz to grams, USD/INR conversion), and domestic premium calculations.
  - Debounced manual rate refresh API (`/api/v1/market/refresh`) with a 60-second cooldown window and honest data freshness badges (`FRESH`, `DELAYED`, `STALE`).
- **Financial News Intelligence & Sync Pipeline**:
  - Sync utility `backend/ml/training/sync_news_analysis.py` processing all 2,735 raw news articles with FinBERT sentiment scoring.
  - REST endpoint `/api/v1/news` with sentiment filtering, gold-relevance badges, and source links.
  - News intelligence tab in frontend terminal displaying real-time financial desk feeds.
- **Alert & Threshold Monitoring**:
  - `AlertRule` model and `AlertService` for tracking target price crosses and domestic premium threshold breaches.
  - REST endpoints at `/api/v1/alerts`.
- **Comprehensive Documentation Suite**:
  - Complete documentation tree in `docs/` covering Product, Architecture, Data, News, ML, Portfolio, Development, and Operations.
  - Exhaustive `README.md`, `AGENTS.md`, `CHANGELOG.md`, and `CONTRIBUTING.md`.

### Changed
- **Database Connection Layer**:
  - Updated `backend/app/db/session.py` to gracefully fall back to SQLite (`data/goldsense.db`) when external PostgreSQL instances are offline.
- **Machine Learning Alignment & Target Repair**:
  - Fixed target column in `train_model.py` to `next_event_gold`.
  - Aligned feature schema to viable daily returns (`return_1d`, `gold_global_inr_per_gram`, `silver_global_inr_per_kg`, `sentiment_score_mean`), dropping unpopulated intraday 15m/1h returns caused by 4.5h collector gaps.
  - Retained 32 fully populated observation rows out of 34 total events.
  - Updated prediction API to provide transparent `EXPERIMENTAL_DATA_COLLECTION` status when dataset size is under 50 events.
- **Frontend Dashboard Terminal**:
  - Complete rewrite of `frontend/app/page.tsx` into an institutional-grade 5-tab financial terminal with responsive Next.js 16 App Router architecture.

### Fixed
- Fixed PostgreSQL connection refusal crash during local test execution by adding SQLite fallback.
- Fixed `KeyError: 'target_gold'` in `train_model.py`.
- Fixed 10 mismatched feature column names in `train_model.py`.
- Fixed 100% row drop in ML pipeline by pruning uncollected 15m/1h returns.
- Fixed hardcoded `assert len(df) == 10` in `test_dataset_alignment.py`, replacing with dynamic invariant `assert len(df) == len(kjpl_df) - 1`.
- Fixed analyzed news cache stall where only 84 of 2,735 articles were processed.

---

## [1.1.0] - 2026-10-20
- Automated GitHub Actions scrapers for KJPL rates, Yahoo Finance market rates, and financial news RSS.
- Initial FinBERT sentiment analysis implementation.
- Basic Next.js dashboard prototype.

---

## [1.0.0] - 2026-10-10
- Initial prototype and exploratory scripts for gold rate tracking.
