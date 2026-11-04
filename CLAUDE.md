# CLAUDE.md — VMD Bullion Intelligence Terminal

## 1. Project Mission & Prime Directives
**VMD Bullion** (formerly GoldSense AI) is a Bloomberg-terminal-inspired Indian physical bullion intelligence platform.

### The Ultimate Aim: Bullion
The core mission is real, institutional physical cash gold & silver market intelligence across India's primary physical jewelry and bullion hubs:
1. **Chennai** (`CHENNAI`) — South India benchmark & MJDTA gold/silver reference rate.
2. **Bengaluru** (`BENGALURU`) — Wholesale & retail tech corridor bullion hub.
3. **Mumbai** (`MUMBAI`) — Zaveri Bazaar national gateway.
4. **Coimbatore** (`COIMBATORE`) — Industrial & manufacturing bullion center.
5. **Hyderabad** (`HYDERABAD`) — High-volume South Indian retail bullion market.
6. **Wholesale Benchmarks**: 1KG 99.99 Pure Gold Bar (`GOLD_1KG_9999`), Spot Silver (`MJDTA_SILVER`), and MJDTA 24K Gold.

### Non-Negotiable Invariants
1. **Zero Fake / Synthetic Data**:
   - Never fabricate missing prices or simulate artificial tick volatility.
   - If markets are closed or prices unchanged, display them as unchanged (`is_changed: false`, `freshness_status: FRESH | DELAYED | STALE`).
   - Distinguish `source_published_at` (when KJPL posted the rate) from `observed_at` (when collector scraped it).
2. **Strict Physical Cash Focus**:
   - Focus on physical cash bullion, import parity, landed duty spreads, and personal vault tracking.
   - GoldSense is NOT a retail e-commerce/POS store (no carts, no checkout, no payment gateways).
3. **Additive, Append-Only Persistence**:
   - Every scrape logs an immutable record in `bullion_rate_observations` and mirrors to `data/kjpl/city_rates.csv`.
   - `bullion_latest_rates` maintains the latest snapshot with price delta.
4. **Multi-User Isolation**:
   - Vault holdings and custom alert rules strictly enforce `user_id` / `X-User-ID`.
5. **Backward Compatibility**:
   - Preserve all existing routes (`/api/bullion/*`, `/api/data-monitor/*`, `/api/kjpl/*`, `/api/market/*`, `/api/news/*`, `/api/portfolio/*`, `/api/alerts/*`, `/api/prediction/*`).
   - Legacy ML models and predictions remain accessible in the backend, but are deprioritized from primary bullion terminal navigation.

---

## 2. Essential Commands

### Environment & Python
```bash
# Virtual environment (Python 3.12)
cd /Users/dhruv/dhruv\ files/gold/GoldSense-AI
source backend/.venv/bin/activate

# Run full backend test suite (104 tests currently passing)
cd backend && pytest tests/ -v

# Run only bullion & collector tests
pytest tests/test_bullion_api.py tests/test_kjpl_city_extraction.py tests/test_kjpl_collector.py -v
```

### Local Backend Server
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# OpenAPI Docs available at http://localhost:8000/docs
```

### Frontend Development
```bash
cd frontend
npm run dev      # Next.js dev server on http://localhost:3000
npm run build    # Production build verification
```

### Database & Alembic Migrations
```bash
# Apply pending migrations (works for both local SQLite and Supabase PostgreSQL)
cd backend
alembic upgrade head

# Create a new migration if schema models are altered
alembic revision --autogenerate -m "describe_change"

# Verify Supabase PostgreSQL connection & write/read-back
DATABASE_URL="postgresql://postgres.[REF]:[PASSWORD]@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres" \
PYTHONPATH=backend python scripts/verify_supabase_connection.py
```

### Scraping & Rate Collectors
```bash
# Run 5-city KJPL collector manually
PYTHONPATH=backend backend/.venv/bin/python scripts/collect_kjpl_csv.py

# Run market benchmark collector (Yahoo Finance spot gold/silver, USD/INR)
PYTHONPATH=backend backend/.venv/bin/python scripts/collect_market_csv.py

# Run news intelligence collector (GDELT / RSS)
PYTHONPATH=backend backend/.venv/bin/python scripts/collect_news_csv.py
```

---

## 3. Architecture & Code Layout

```
GoldSense-AI/
├── backend/
│   ├── app/
│   │   ├── api/routes/
│   │   │   ├── bullion.py          # /api/bullion/* (city rates, matrix, history, summary)
│   │   │   ├── data_monitor.py     # /api/data-monitor/* (telemetry, collector health)
│   │   │   ├── market.py           # /api/market/* (spot gold/silver, USD/INR)
│   │   │   ├── news.py             # /api/news/* (live financial news & macro sentiment)
│   │   │   ├── portfolio.py        # /api/portfolio/* (vault holdings & valuation)
│   │   │   └── alerts.py           # /api/alerts/* (price alert rules)
│   │   ├── db/
│   │   │   ├── base.py             # DeclarativeBase with all models registered
│   │   │   └── session.py          # Resilient connection pooler + URI normalization
│   │   ├── models/
│   │   │   ├── bullion.py          # BullionCity, BullionProduct, BullionRateObservation, BullionLatestRate
│   │   │   ├── collector_run.py    # CollectorRun, DataSourceStatus
│   │   │   └── portfolio.py        # PortfolioHolding, AlertRule
│   │   └── services/
│   │       ├── kjpl/
│   │       │   ├── parser.py       # City extractor & normalizer (HTML table & JS script regex)
│   │       │   └── persistence.py  # Dual DB + CSV append-only observation recorder
│   │       └── bullion_service.py  # Import parity, city matrix, spread calculations
│   ├── migrations/versions/        # Alembic revision history (0f1a9481a06e: VMD Bullion tables)
│   └── tests/                      # 104 comprehensive unit & integration tests
├── frontend/
│   ├── app/
│   │   ├── layout.tsx              # Terminal root layout with dark theme & monospace font
│   │   ├── globals.css             # Bloomberg amber (#f59e0b), emerald (#10b981), terminal styling
│   │   └── page.tsx                # Terminal UI: 5-city live ticker, India Bullion Desk,
│   │                               # matrix comparison, import parity, news, vault, data monitor
├── scripts/
│   ├── collect_kjpl_csv.py         # 5-city KJPL collector with 3x retry + SQLite/Supabase persistence
│   ├── verify_supabase_connection.py # Supabase PostgreSQL diagnostic & verification script
│   └── validate_pipeline_outputs.py # ML artifact validation
└── .github/workflows/
    └── kjpl-collector.yml          # GitHub Actions 5-city automated cloud collector (runs on schedule)
```

---

## 4. Guidance on Altering & Extending the Platform

When altering or extending VMD Bullion, follow these specific guidelines:

### What You CAN Alter & Improve:
1. **Frontend Modularization**:
   - `frontend/app/page.tsx` is currently a comprehensive single-file terminal. You may split it into modular subcomponents in `frontend/components/bullion/` (`TickerTape.tsx`, `BullionDesk.tsx`, `CityMatrix.tsx`, `ImportParityDesk.tsx`, `VaultManager.tsx`, `DataMonitor.tsx`) for cleaner maintainability.
2. **Institutional Analytics**:
   - Add MCX vs Spot basis spread tracking (`KJPL Cash - MCX Near Month`).
   - Add city spread heatmaps (e.g. Chennai vs Mumbai arbitrage spread in INR/10g).
   - Add custom duty structure simulation in the Import Parity Desk (allowing users to toggle BCD, AIDC, and Agriculture Cess rates).
3. **Database & Collector Performance**:
   - Add Redis/in-memory caching for `/api/bullion/latest` if request throughput demands it.
   - Add alerts webhooks (Telegram/WhatsApp/Email) when a city rate changes.

### What You MUST NOT Alter:
1. **Never synthesize prices**: If KJPL or an upstream source returns 403 or is offline, log `UPSTREAM_UNAVAILABLE` and retain existing verified prices. Do not generate synthetic drift.
2. **Never break existing routes**: Mobile apps, web components, and cron workflows depend on `/api/bullion/*`, `/api/kjpl/*`, and `/api/market/*`.
3. **Never ask user for database credentials in chat**: All credentials belong in environment variables (`DATABASE_URL`, `SUPABASE_DATABASE_URL`).

---

## 5. Supabase Production Connection Checklist
When ready to connect to production Supabase PostgreSQL:
1. Set `DATABASE_URL` in environment (or `SUPABASE_DATABASE_URL` in GitHub Secrets).
2. Run `alembic upgrade head` to apply all migrations.
3. Run `PYTHONPATH=backend python scripts/verify_supabase_connection.py` to confirm table integrity, seeding, and live transactional write/read-back.
