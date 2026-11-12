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

# Run full backend test suite
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/ -v

# Run only bullion & collector tests
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/test_bullion_api.py backend/tests/test_kjpl_city_extraction.py backend/tests/test_kjpl_collector.py -v
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
# Apply pending migrations (works for both local SQLite and Neon PostgreSQL)
cd backend
alembic upgrade head

# Create a new migration if schema models are altered
alembic revision --autogenerate -m "describe_change"

# Verify Neon PostgreSQL connection & write/read-back
DATABASE_URL="postgresql://[USER]:[PASSWORD]@[NEON-ENDPOINT].neon.tech/[DB]?sslmode=require" \
PYTHONPATH=backend python scripts/verify_neon_connection.py
```

### KJPL Collectors (Exclusive Upstream Source)
```bash
# Run Pipeline A: 5-city & MJDTA KJPL HTML collector manually
PYTHONPATH=backend backend/.venv/bin/python scripts/collect_kjpl_csv.py

# Run Pipeline B: Live KJPL WebSocket + kjpl.txt worker (single-writer via fcntl lock)
PYTHONPATH=backend backend/.venv/bin/python scripts/kjpl_live_worker.py --once

# Run news intelligence collector (GDELT / RSS)
PYTHONPATH=backend backend/.venv/bin/python scripts/collect_news_csv.py
```
> **Note:** Yahoo Finance (`yfinance` / `scripts/collect_market_csv.py`) is permanently decommissioned per `docs/architecture/ADR_001_KJPL_ORACLE_NEON_VERCEL.md`. Spot Gold, Spot Silver, and USD/INR parity are sourced exclusively from KJPL.

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
│   │       │   ├── city_parser.py  # HTML MJDTA + Type 1/2/3/LBMA parser & validator
│   │       │   ├── validator.py    # Unit/purity bounds & historical quarantine rules
│   │       │   ├── live_worker.py  # Oracle Pipeline B WS + kjpl.txt worker
│   │       │   └── persistence.py  # Atomic Decimal DB + optional CSV mirror recorder
│   │       └── bullion_service.py  # KJPL spot parity, city matrix, consolidated dashboard
│   ├── migrations/versions/        # Alembic revisions through a7c3e91b42d0 (Numeric + Quarantine)
│   └── tests/                      # Unit & integration tests (backend/tests/)
├── frontend/
│   ├── app/
│   │   ├── layout.tsx              # Terminal root layout with dark theme & monospace font
│   │   ├── globals.css             # Bloomberg amber (#f59e0b), emerald (#10b981), terminal styling
│   │   └── page.tsx                # Terminal UI: SSE live stream, 5-city ticker, parity, vault, monitor
│   └── components/bullion/
│       └── KjplLiveDeskPanel.tsx   # KJPL Live Terminal Type 1/2 & LBMA USD Desk
├── scripts/
│   ├── collect_kjpl_csv.py         # Pipeline A MJDTA collector -> Neon PostgreSQL (NullPool)
│   ├── kjpl_live_worker.py         # Pipeline B Oracle systemd single-writer worker
│   ├── remediate_historical_data.py # Quarantines corrupt/duplicate historical CSV & DB rows
│   ├── verify_neon_connection.py   # Neon PostgreSQL diagnostic & write/read-back verifier
│   └── validate_pipeline_outputs.py # ML artifact validation
└── .github/workflows/
    ├── kjpl-collector.yml          # Pipeline A MJDTA collector -> NEON_DATABASE_URL (no git commits)
    ├── market-collector.yml        # Decommissioned Yahoo stub (manual guard only)
    ├── news-collector.yml          # News collector (03, 09, 15, 21 UTC)
    └── pipeline-update.yml         # Post-news feature/eval pipeline & artifact validator
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
3. **Never ask user for database credentials in chat**: All credentials belong in environment variables (`DATABASE_URL`, `NEON_DATABASE_URL`).

---

## 5. Neon + Oracle + Vercel Production Checklist (ADR-001)
When ready to connect the live **₹0/month stack** (superseding Supabase + Render):
1. Set `NEON_DATABASE_URL` in GitHub Repository Secrets (for `.github/workflows/kjpl-collector.yml`). Wait for explicit user approval before retiring legacy `SUPABASE_DATABASE_URL`.
2. On Oracle Cloud Always Free VM, run `alembic upgrade head` against Neon `DATABASE_URL` (`sslmode=require`), then run `PYTHONPATH=backend python scripts/verify_neon_connection.py`.
3. Enable `deploy/oracle/vmd-bullion-api.service`, `deploy/oracle/vmd-kjpl-worker.service`, and `deploy/oracle/nginx-vmd-bullion.conf`.
4. Deploy `frontend/` to Vercel Hobby with `NEXT_PUBLIC_API_BASE_URL` pointing to the Oracle API URL.

---

## 6. Remediated Data Status (Updated Nov 11, 2026)

### Valid vs Quarantined Data Counts on `develop`
- `data/kjpl/kjpl_rates.csv`: **47 valid rows** (6 Oct 31 duplicates moved to `data/kjpl/quarantined_kjpl_rates.csv`)
- `data/kjpl/city_rates.csv`: **8 valid rows** (125 corrupt/fixture/duplicate rows quarantined into `data/kjpl/quarantined_city_rates.csv`)
- `data/goldsense.db`: Rebuilt cleanly via Alembic (`a7c3e91b42d0`) with **8 valid** observations seeded.
- `backend/ml/data/processed/evaluation_report.json`: **42 / 50 usable ML events** (`INSUFFICIENT_DATA_FOR_SUPERVISED_TRAINING`, 8 more unique trading events needed before enabling ML inference)

### Architecture Focus
- Modularize remaining oversized UI tabs out of `frontend/app/page.tsx` alongside `KjplLiveDeskPanel.tsx`.
- Wire live `NEON_DATABASE_URL`, Oracle VM, and Vercel Hobby endpoints once infrastructure credentials are provisioned.
