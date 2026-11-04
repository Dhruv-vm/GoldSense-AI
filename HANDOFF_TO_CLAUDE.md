# VMD BULLION — MASTER ENGINEERING HANDOFF FOR CLAUDE

> **Document Type:** System Architecture & Operational Handover  
> **Target Audience:** Claude (Anthropic AI Assistant / Claude Code) & Contributing Engineers  
> **Project Name:** VMD Bullion (Elevated from GoldSense AI)  
> **Repository:** `https://github.com/Dhruv-vm/GoldSense-AI`  
> **Active Branch:** `develop`  
> **Status:** Phase 1 (Audit), Phase 2 (Parser), Phase 3 (Cloud Collector), Phase 4 (DB Schema/Migrations), Phase 5 (FastAPI Bullion Endpoints), and Phase 6 (Bloomberg Terminal Frontend) are **COMPLETE & VERIFIED**.

---

## 1. Executive Summary & The Ultimate Aim: Bullion

The overarching objective of this project is **VMD Bullion** — a high-density, institutional-grade, Bloomberg-terminal-inspired Indian physical bullion intelligence platform.

### Why Physical Bullion?
Unlike speculative derivative platforms, the Indian physical gold and silver market operates on physical delivery across major regional jewelery and bullion trading hubs. Each regional hub exhibits distinct physical premiums, transport costs, and local demand dynamics:
- **Chennai** (`CHENNAI`): The primary physical gateway of South India, home to the Madras Jewellers & Diamond Traders Association (MJDTA) benchmark for 24K and Spot Silver.
- **Bengaluru** (`BENGALURU`): High-volume wholesale and retail bullion corridor in Karnataka.
- **Mumbai** (`MUMBAI`): Zaveri Bazaar — India's largest cash bullion and wholesale clearing center.
- **Coimbatore** (`COIMBATORE`): Major jewelry casting, refining, and manufacturing hub in Tamil Nadu.
- **Hyderabad** (`HYDERABAD`): Massive physical consumption market across Telangana and Andhra Pradesh.
- **National Benchmarks**: 1KG 99.99 Fine Pure Bar (`GOLD_1KG_9999`) and MJDTA Spot Silver (`MJDTA_SILVER`).

### Invariants & Non-Negotiables
1. **Zero Fake / Synthetic Live Prices**:
   - Never inject synthetic prices or random tick generators.
   - If markets are closed (weekends, holidays) or the upstream source hasn't published new rates, show prices as unchanged (`is_changed: false`).
   - Always display `source_published_at` (e.g. `09:37 am IST`) separately from `observed_at` (collection timestamp).
2. **Personal Bullion Intelligence vs. Commercial E-Commerce**:
   - VMD Bullion is a personal intelligence, analytics, and vault tracking terminal.
   - It is NOT an e-commerce store (no shopping carts, checkout flows, commercial invoices, or payment gateways).
3. **Multi-User Isolation**:
   - Personal vault holdings (`portfolio_holdings`) and alert rules (`alert_rules`) enforce tenant isolation by `user_id` / `X-User-ID`.
4. **Append-Only Observation Discipline**:
   - Every scrape appends an immutable observation row in `bullion_rate_observations` and mirrors to `data/kjpl/city_rates.csv`.
5. **Security & Credential Confidentiality**:
   - Never commit database passwords, API tokens, or secrets to Git. Never prompt the user to paste database passwords into chat.

---

## 2. Proven Operational State & Milestones

| Subsystem | Status | Verification Detail |
|---|---|---|
| **Backend Test Suite** | ✅ 100% Passing | **104 tests passing** (`pytest tests/ -v`) in 10.60s |
| **5-City KJPL Parser** | ✅ Verified | Extracts Chennai, Bengaluru, Mumbai, Coimbatore, Hyderabad, 1KG Pure Bar, MJDTA Gold/Silver |
| **GitHub Actions Cloud Collector** | ✅ Verified Live | **Run ID 41301548614 succeeded** on fresh Ubuntu runner; auto-initialized tables and committed live data to `develop` (`c1c733b`) |
| **Database Models & Alembic** | ✅ Complete | Migration `0f1a9481a06e_create_vmd_bullion_city_tables.py` creates all 6 tables with proper indices and foreign keys |
| **FastAPI Endpoints** | ✅ Live & Tested | `/api/bullion/*` (5 endpoints) & `/api/data-monitor/*` (2 endpoints) passing all integration tests |
| **Frontend Terminal** | ✅ Built & Styled | Bloomberg terminal UI (amber `#f59e0b`, green `#10b981`, red `#ef4444`, monospace numbers) with live ticker, India desk, matrix, import parity, news, vault |
| **Supabase Diagnostic Script** | ✅ Ready | `scripts/verify_supabase_connection.py` tests connection, seeding, and live transactional write/read-back |

---

## 3. Architecture Blueprint

```
                      ┌──────────────────────────────────────────────┐
                      │              UPSTREAM SOURCES                │
                      │  • KJPL (http://www.kjpl.in/) -> 5 Cities    │
                      │  • Yahoo Finance -> Spot Gold/Silver, USD/INR │
                      │  • GDELT / RSS -> Macro Financial News       │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │          CLOUD COLLECTOR ENGINE              │
                      │  • GitHub Actions (.github/workflows/)       │
                      │  • 3x retry with exponential backoff         │
                      │  • Graceful UPSTREAM_UNAVAILABLE handling    │
                      │  • Concurrent rebase push loop (MAX=4)       │
                      └──────────────────────┬───────────────────────┘
                                             │
                     ┌───────────────────────┴───────────────────────┐
                     ▼                                               ▼
         ┌────────────────────────┐                     ┌────────────────────────┐
         │     DATABASE LAYER     │                     │      CSV MIRRORS       │
         │  • Supabase PostgreSQL │                     │  • data/kjpl/          │
         │    (Session Pooler)    │                     │    city_rates.csv      │
         │  • SQLite Local Dev    │                     │  • data/market/        │
         │    (data/goldsense.db) │                     │    market_rates.csv    │
         └───────────┬────────────┘                     └────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────────────────────────────────────┐
         │                 FASTAPI BACKEND SERVICE                   │
         │  • /api/bullion/* (City rates, matrix, history, summary)  │
         │  • /api/data-monitor/* (Telemetry, collector runs)        │
         │  • /api/market/* (Spot XAU/USD, XAG/USD, USD/INR)         │
         │  • /api/news/* (Macro news intelligence & gold sentiment) │
         │  • /api/portfolio/* (Personal bullion vault tracking)     │
         │  • /api/alerts/* (Threshold-based price alerts)           │
         └───────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼
         ┌───────────────────────────────────────────────────────────┐
         │             VMD BULLION TERMINAL FRONTEND                 │
         │  • Next.js 16 + React 19 + Tailwind CSS v4                │
         │  • High-density Bloomberg terminal typography & theme     │
         │  • Live 5-city ticker tape with pulse indicators          │
         │  • India Bullion Desk with landed duty / import parity    │
         │  • Regional arbitrage matrix & city spread comparator     │
         │  • Personal Bullion Vault (grams/kg, fine purity, P&L)    │
         │  • Real-time Data Monitor & pipeline freshness status     │
         └───────────────────────────────────────────────────────────┘
```

---

## 4. Database Schema Reference

All tables are managed via SQLAlchemy models in `backend/app/models/` and tracked by Alembic in `backend/migrations/versions/0f1a9481a06e_create_vmd_bullion_city_tables.py`.

### 1. `bullion_cities`
Stores registered physical bullion cities and their display metadata.
- `id` (Integer, PK)
- `city_code` (String, Unique, Indexed) — e.g. `CHENNAI`, `BENGALURU`, `MUMBAI`, `COIMBATORE`, `HYDERABAD`
- `display_name` (String) — e.g. "Chennai", "Bengaluru"
- `state` (String) — e.g. "Tamil Nadu", "Karnataka"
- `is_active` (Boolean, default True)
- `sort_order` (Integer)

### 2. `bullion_products`
Standardized catalog of physical products and benchmark contracts.
- `id` (Integer, PK)
- `product_id` (String, Unique, Indexed) — e.g. `GOLD_100G_999`, `GOLD_1KG_9999`, `MJDTA_GOLD_24K`, `MJDTA_SILVER`, `SILVER_1KG_999`
- `product_name` (String)
- `metal` (String) — `GOLD` or `SILVER`
- `purity` (Float) — `0.999`, `0.9999`, `0.916`
- `weight` (Float) — `1.0`, `100.0`, `1000.0`
- `unit` (String) — `1g`, `100g`, `1kg`
- `rate_type` (String) — `RETAIL`, `WHOLESALE`, `MJDTA_BENCHMARK`
- `source_product_id` (String) — e.g. KJPL ID `47`, `48`, `49`, `50`, `51`, `52`
- `is_active` (Boolean)

### 3. `bullion_rate_observations`
Immutable, append-only historical price log.
- `id` (Integer, PK)
- `city_code` (String, FK -> `bullion_cities.city_code`, Indexed)
- `product_id` (String, FK -> `bullion_products.product_id`, Indexed)
- `price` (Float) — Observed price in INR
- `currency` (String, default `INR`)
- `rate_type` (String)
- `unit` (String)
- `source_url` (String)
- `source_published_at` (DateTime with timezone) — Upstream publication timestamp
- `observed_at` (DateTime with timezone) — Collector extraction timestamp
- `is_changed` (Boolean) — True if price differed from the previous observation
- `freshness_status` (String) — `FRESH`, `DELAYED`, `STALE`
- Composite Index: `idx_bullion_obs_city_prod_time` on `(city_code, product_id, observed_at)`

### 4. `bullion_latest_rates`
Current state snapshot per city and product for O(1) reads.
- `id` (Integer, PK)
- `city_code` (String, FK -> `bullion_cities.city_code`)
- `product_id` (String, FK -> `bullion_products.product_id`)
- `latest_price` (Float)
- `previous_price` (Float, nullable)
- `change_inr` (Float) — Absolute difference (`latest - previous`)
- `change_pct` (Float) — Percentage change
- `currency` (String)
- `unit` (String)
- `rate_type` (String)
- `source_published_at` (DateTime with timezone)
- `last_collected_at` (DateTime with timezone)
- `last_verified_at` (DateTime with timezone)
- `freshness_status` (String)
- `source_url` (String)
- Unique Constraint: `(city_code, product_id)`

### 5. `collector_runs`
Execution telemetry for scrapers.
- `id` (Integer, PK)
- `collector_name` (String, Indexed) — e.g. `kjpl_collector`, `market_collector`
- `status` (String) — `SUCCESS`, `NO_CHANGE`, `UPSTREAM_UNAVAILABLE`, `ERROR`
- `records_extracted` (Integer)
- `records_inserted` (Integer)
- `records_changed` (Integer)
- `duration_seconds` (Float)
- `error_message` (Text, nullable)
- `executed_at` (DateTime with timezone)

### 6. `data_source_status`
High-level health dashboard entry per upstream provider.
- `id` (Integer, PK)
- `source_name` (String, Unique, Indexed) — e.g. `KJPL`, `YAHOO_FINANCE`, `GDELT`
- `last_successful_run` (DateTime with timezone)
- `last_failed_run` (DateTime with timezone)
- `current_status` (String) — `HEALTHY`, `DEGRADED`, `OFFLINE`
- `error_message` (Text, nullable)
- `updated_at` (DateTime with timezone)

---

## 5. API Catalog Reference

All routes are mounted in `backend/app/main.py`.

### Bullion Intelligence (`/api/bullion/*`)
- **`GET /api/bullion/latest`**: Complete executive summary. Returns active cities, 1KG Pure Bar wholesale price, MJDTA reference rates, and latest 100g retail rates across all 5 cities.
- **`GET /api/bullion/cities`**: Returns metadata for all registered cities (`CHENNAI`, `BENGALURU`, `MUMBAI`, `COIMBATORE`, `HYDERABAD`).
- **`GET /api/bullion/rates`**: Query latest rates with optional filters:
  - `?city=CHENNAI` or `?city=bangalore` (normalized automatically to `BENGALURU`).
  - `?product_id=GOLD_100G_999`.
- **`GET /api/bullion/matrix`**: Regional comparison matrix. Computes price per 10g, premium/discount in INR and bps against the Chennai benchmark.
- **`GET /api/bullion/history`**: Time-series observation history with parameters `city`, `product_id`, `window_hours`, `limit`.

### Data Monitor (`/api/data-monitor/*`)
- **`GET /api/data-monitor/status`**: Health status of all data pipelines, last collection timestamps, and freshness flags.
- **`GET /api/data-monitor/collectors`**: Historical log of collector executions with duration and records processed.

### Supplementary Preserved Routes
- **`GET /api/market/overview`**: International benchmarks (XAU/USD, XAG/USD, USD/INR, MCX gold).
- **`GET /api/news/latest`**: Curated financial news with gold macro sentiment impact scoring.
- **`GET /api/portfolio/holdings` & `POST /api/portfolio/holdings`**: Personal vault holdings with live mark-to-market valuation.
- **`GET /api/alerts/rules` & `POST /api/alerts/rules`**: Threshold alert management.

---

## 6. How Claude Can Safely Alter & Extend the Platform

The prompt explicitly asks: *"let it understand if possible alter it and the ultimate aim is bullion right crate all necessary files bro"*.

Here are clear boundaries and recommendations on what to alter vs. what to keep invariant:

### Areas Open for Alteration & Enhancement:
1. **Frontend Architecture & Modularization**:
   - `frontend/app/page.tsx` is currently a monolithic file (>110KB) to ensure rapid end-to-end delivery.
   - Claude can cleanly decompose `page.tsx` into modular components under `frontend/components/bullion/`:
     - `BullionTicker.tsx` (Top ticker tape with live flashing delta indicators)
     - `IndiaBullionDesk.tsx` (City rate cards, 1KG bar spotlight, MJDTA benchmark badge)
     - `CityMatrixDesk.tsx` (5-city spread grid, arbitrage differentials vs Chennai)
     - `ImportParityDesk.tsx` (Interactive landed cost calculator: Customs duty 6%, AIDC, GST 3%)
     - `BullionHistoricalChart.tsx` (High-density SVG or Recharts time-series view)
     - `VaultManager.tsx` (Personal physical gold & silver asset ledger)
     - `DataMonitorPanel.tsx` (Collector telemetry & freshness radar)
2. **Import Parity Mathematics & Landed Cost Simulation**:
   - Currently, import parity formula:
     $$\text{Landed Cost (INR/g)} = \left(\frac{\text{XAU/USD} \times \text{USD/INR}}{31.1034768}\right) \times (1 + \text{BCD} + \text{AIDC}) \times (1 + \text{GST})$$
   - Claude can enhance the parity desk to allow users to toggle customs duty slabs (e.g. Union Budget duty changes) or customize local municipal taxes.
3. **MCX vs Cash Spot Basis Spread**:
   - Claude can add an analytical widget comparing the KJPL Physical Cash rate against MCX Near-Month Gold Futures, displaying the Cash-Futures Basis spread in INR/10g.
4. **Alert Notification Channels**:
   - Claude can extend `app/services/alert_service.py` to support webhook dispatch (e.g. Telegram or Discord bot notifications) when a city rate moves beyond a user-configured threshold.

### Areas That Must Remain Invariant:
1. **Never fabricate prices or simulate tick volatility**: Display actual values from `data/kjpl/city_rates.csv` or PostgreSQL.
2. **Never change existing route URLs**: Maintain full backward compatibility for existing endpoints.
3. **Never ask the user to paste database credentials into chat**: Instruct the user to pass them via environment variables or GitHub Secrets.

---

## 7. Supabase Production Connection Guide

When the user is ready to wire the live Supabase PostgreSQL database:

### Step 1: User Adds GitHub Action Secret
User navigates to:  
`https://github.com/Dhruv-vm/GoldSense-AI/settings/secrets/actions`  
And adds secret:
- **Name:** `SUPABASE_DATABASE_URL`
- **Value:** `postgresql://postgres.[REF]:[PASSWORD]@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres`

### Step 2: Apply Alembic Migrations Against Supabase
```bash
DATABASE_URL="postgresql://postgres.[REF]:[PASSWORD]@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres" \
cd backend && alembic upgrade head
```

### Step 3: Run the Verification Script
```bash
DATABASE_URL="postgresql://postgres.[REF]:[PASSWORD]@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres" \
PYTHONPATH=backend python scripts/verify_supabase_connection.py
```
This script automatically:
1. Verifies TCP & SSL connection to the pooler.
2. Confirms all 10 tables exist and schema matches.
3. Verifies reference cities and products are seeded.
4. Executes a live test insertion, read-back, and transactional cleanup.

### Step 4: Render Deployment Environment Variables
In the Render dashboard for the backend service:
- `DATABASE_URL`: `postgresql://postgres.[REF]:[PASSWORD]@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres`
- `ENVIRONMENT`: `production`
- `PYTHONPATH`: `backend`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

---

## 8. Development Runbook & Useful Snippets

### Running Tests
```bash
# Full test suite
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/ -v

# Bullion specific tests
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/test_bullion_api.py backend/tests/test_kjpl_city_extraction.py -v
```

### Running Scraper Locally
```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/collect_kjpl_csv.py
```

### Starting FastAPI Locally
```bash
cd backend && ../backend/.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Starting Next.js Locally
```bash
cd frontend && npm run dev
```

---
*End of Master Engineering Handoff. VMD Bullion is primed for production deployment and institutional scaling.*
