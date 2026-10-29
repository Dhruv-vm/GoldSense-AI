# CHANGELOG

All notable changes to the **GoldSense AI** platform are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0-develop] - 2026-10-29

### Added
- **Freshness-First Live News Signal & Commodity Impact Engine**:
  - `backend/app/services/sentiment/gold_impact.py`: Evaluates domain-specific bullion directional impact (`BULLISH`, `BEARISH`, `MIXED`, `UNCERTAIN`), attributing macroeconomic events across Fed monetary policy, US Dollar FX, safe-haven geopolitics, physical retail demand, central bank reserves, and momentum.
  - Formulates exponential recency decay $w = e^{-\Delta t / 12}$ (half-life of 12 hours) and semantic token stem clustering (`extract_cluster_key`) to deduplicate syndicated wire reprints (e.g. Reuters/PTI duplicates).
  - Grounded explanatory evidence rationale for every scored story.
- **Real-Time Live Signal Aggregator & Endpoints**:
  - `backend/app/services/sentiment/live_signal.py`: Aggregates fresh articles strictly within a configurable recency window (default: 24h, support for 48h/72h).
  - Compares news directional consensus against live intraday market movements (`market_vs_news_alignment`: `AGREES_BULLISH`, `AGREES_BEARISH`, `DIVERGES`, `NEUTRAL`).
  - Transparent safety guard returning `INSUFFICIENT_FRESH_RELEVANT_NEWS` if fewer than 2 distinct fresh story clusters exist.
  - Endpoint `GET /api/news/live-signal?window_hours=24` returning structured consensus metrics, macro driver distributions, and representative articles.
  - Endpoint `GET /api/news/latest?window_hours=24&limit=30` enriched with bullion impact badges, macro drivers, confidence, and evidence rationale.
- **Decoupled Architecture in ML Predictor & Frontend**:
  - Updated `backend/app/services/prediction/predictor.py` to expose the fresh news intelligence signal cleanly decoupled alongside the market macro snapshot, preventing noisy sentiment embeddings from corrupting the low-sample quantitative price regression.
  - Upgraded Next.js 16 frontend terminal (`frontend/app/page.tsx`):
    - Added recency window toggle (`24h (Live)`, `48h`, `72h`).
    - Added Live Macro Consensus banner displaying net bullion direction, confidence, market alignment, and macro driver counts.
    - Upgraded News Feed with bullion directional impact badges (`BULLISH FOR GOLD`, `BEARISH FOR GOLD`, `MIXED`), driver tags, confidence ratings, and evidence rationale.
    - Added Live News Intelligence card to AI Predictions tab.
- **Walk-Forward Fresh News Evaluation**:
  - `backend/ml/training/fresh_news_walk_forward.py`: Zero-lookahead 21-fold backtest comparing Naive Persistence vs. Market-Only vs. Fresh News-Only vs. Market + Fresh News.
  - Confirmed bullion directional impact rules improve news-only directional accuracy from 33.3% to 38.1%, while market features dominate short-horizon pricing (61.9% directional accuracy, ₹74.29 RMSE).
- **Test Suite Expansion**:
  - Added `backend/tests/test_gold_impact_and_live_signal.py` testing directional commodity logic, syndicated clustering, recency window enforcement, API endpoints, and insufficient fresh news guards.
  - Expanded backend test suite to **80 passing tests (100% pass rate)**.

---

## [2.1.0-develop] - 2026-10-29

### Added
- **News Predictive Signal Research Deliverable**:
  - Comprehensive empirical audit in `docs/ml/NEWS_PREDICTIVE_SIGNAL_RESEARCH.md` investigating 2,815 articles across 21 out-of-sample walk-forward folds.
  - Comparative benchmarks: Naive Persistence (MAE: ₹61.90/g), Market-Only (MAE: ₹63.96/g, Directional Acc: 52.4%), News-Only (MAE: ₹69.26/g, Directional Acc: 33.3%), and Market + News (MAE: ₹65.59/g, Directional Acc: 47.6%).
  - Detailed domain analysis identifying the FinBERT commodity polarity mismatch (e.g. strong dollar evaluated as positive financial language but bearish for bullion).
  - Machine-readable evaluation export in `backend/ml/data/processed/news_signal_experiment.json`.
- **Daily Automated Pipeline & Evaluation Workflow**:
  - Dedicated GitHub Actions workflow `.github/workflows/pipeline-update.yml` running daily at `38 14 * * *` UTC (8:08 PM IST) after morning and evening market publication windows.
  - Executes `update_pipeline.py`, cleans events, builds market features, scores news via FinBERT, rebuilds training matrix, and benchmarks walk-forward baseline metrics.
  - Bounded retry push strategy with rebase to prevent non-fast-forward failures against concurrent collector commits.
- **Pipeline Output Integrity Validator**:
  - Automated integrity check `scripts/validate_pipeline_outputs.py` asserting non-empty datasets, monotonic timestamps, expected feature columns, and zero-lookahead invariants across all 5 generated artifacts.
  - Unit test suite `backend/tests/test_pipeline_validation.py` expanding test coverage to **69 passing tests (100% pass rate)**.

### Fixed
- **Market Data Collector Concurrency**:
  - Added `git pull --rebase origin develop` and explicit `git push origin develop` to `.github/workflows/market-collector.yml`, eliminating push rejection when running in parallel with news ingestion.
- **Dynamic Sample-Count Test Assertion**:
  - Replaced hardcoded sample count in `tests/test_api_endpoints.py` with dynamic range assertion, allowing seamless accumulation of genuine daily events.

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
