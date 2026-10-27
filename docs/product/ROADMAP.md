# Product Roadmap

## Phase 1: Foundation & Data Normalization (Completed)
- [x] Initial automated collectors for KJPL and Yahoo Finance.
- [x] Flat CSV data architecture in `data/`.
- [x] FinBERT news sentiment extraction pipeline.

## Phase 2: Master Build & Core Consolidation (Current - v2.0.0-develop)
- [x] Resilient database session with automatic SQLite fallback.
- [x] Unified `DataService` with Troy ounce to gram conversion and domestic premium computation.
- [x] Personal Bullion Portfolio tracker with fine weight calculation and market mark-to-market valuation.
- [x] News cache synchronization utility (`sync_news_analysis.py`).
- [x] Zero-lookahead feature schema alignment and honest sample count checks ($N < 50$).
- [x] Institutional-grade 5-tab Next.js financial terminal with responsive UI.
- [x] 100% backend test pass rate across 59 unit and integration tests.

## Phase 3: ML Maturation & Expansion (Target: Q1 2027)
- [ ] Accumulate 100+ daily market events in `gold_training_dataset.csv`.
- [ ] Transition ML model from experimental collection to live daily inference with confidence intervals.
- [ ] Integrate Indian macroeconomic indicators (RBI policy rates, local consumer price indices).
- [ ] Multi-tenant authentication layer (OAuth2 / JWT session management).
- [ ] Push notification service for price alert triggers (Web push / Telegram bot).
