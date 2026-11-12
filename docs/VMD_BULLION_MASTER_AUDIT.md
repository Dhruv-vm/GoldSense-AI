# VMD BULLION — MASTER ENGINEERING AUDIT REPORT (PHASE 0)

> **Audit Date:** 2026-11-11  
> **Repository:** `https://github.com/Dhruv-vm/GoldSense-AI`  
> **Branch Audited:** `develop` (HEAD `06fdf0a`, clean working tree)  
> **Target Architecture:** Exclusive KJPL Source · Oracle Cloud Always Free (API + Continuous Worker) · Neon PostgreSQL · Vercel Hobby (Frontend) · GitHub Actions (Scheduled MJDTA Collector Only) · **₹0/month Recurring Target**

---

## Executive Summary

A full-stack codebase, database, CSV persistence, GitHub workflow, security, and live-upstream inspection of **VMD Bullion** (branch `develop`) revealed **10 categories of structural and data-integrity defects**. Most critically:
1. **Upstream Source & Non-KJPL Contamination:** The app still relies on **Yahoo Finance (`yfinance`)** for `XAUUSD`, `XAGUSD`, and `USDINR` (`scripts/collect_market_csv.py`, `backend/app/services/market/client.py`, `backend/app/services/data_service.py`, `.github/workflows/market-collector.yml`), violating the exclusive-KJPL data-source rule—even though **KJPL itself directly publishes `SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR`, `GOLDDEC`, `SILVERDEC`, LBMA AM/PM fixes, MJDTA rates, and bank costing parameters**.
2. **Broken Live KJPL City Extraction:** `backend/app/services/kjpl/city_parser.py` inspects static HTML tables and looks for nonexistent `<script>` tags with `com_name`/`com_id`. On live `http://www.kjpl.in/`, `#liveratetable` cells are **empty in initial HTML** and hydrated dynamically via WebSocket (`ws://www.kjpl.in/ws`, `bcrate_Type == 5`) and text snapshot (`http://www.kjpl.in/client/kjpl.txt`). Falling back to `valid_numbers[-1]` across concatenated hidden `<div>` elements caused severe corruption (e.g., `100.0`, `51.0`, `52.0` from `com_display_purity`/`com_id`, `200.0`/`210.0` silver under gold, and `4043.65` / `51.99` LBMA USD/oz under INR MJDTA).
3. **Database Provider Pivot:** Active code and docs reference **Supabase** and **Render** (`backend/app/db/session.py`, `scripts/verify_supabase_connection.py`, `.github/workflows/kjpl-collector.yml`, `CLAUDE.md`, `HANDOFF_TO_CLAUDE.md`) and use `Float` columns instead of `Numeric`/`Decimal`.
4. **Duplicate Writers & Git-as-DB:** Both APScheduler inside FastAPI (`backend/app/jobs/scheduler.py`) and 4 GitHub Actions workflows write concurrently and commit CSV data directly back into `develop`.
5. **Test Isolation Failure Causing Live Corruption:** `backend/tests/test_kjpl_city_extraction.py` directly deletes rows in live `data/goldsense.db` and appends fixture observations (`13085000.0`) into `data/kjpl/city_rates.csv` (explaining the 9 identical duplicate rows on `2026-10-31` and bogus Nov 10 `goldsense.db` rows).

---

## Live KJPL Upstream Discovery Summary (Verified 2026-11-11 IST)

Probing `http://www.kjpl.in/`, `http://www.kjpl.in/assets/js/custom/booking.js?vs=1.0.1`, `http://www.kjpl.in/client/kjpl.txt`, and `ws://www.kjpl.in/ws` from an interactive check established the actual KJPL live mechanism:

| Feed / Mechanism | Endpoint / Selector | Observed Payload & Verified Semantics |
|---|---|---|
| **Static HTML MJDTA** | `http://www.kjpl.in/` (`.gold-rate`, `.silver-rate`, Table 10/11/14/15 `.chennairate_table`) | Publishes MJDTA Gold (`13015`), Silver (`200`), MJDTA With GST (`13405.45` / `206.00`), and **full date+time** `UPDATED: 11-11-2026 09:37:32 am`. |
| **Static HTML LBMA London Fix** | Table 9 / 13 (`.chennairate_table`) | Publishes `GOLD AM Fix: ($) 4073.70` (`10-11-2026 04:00:00 pm`), `GOLD PM Fix: ($) 4050.90`, `SILVER Fix: ($) 52.2850`. Units are **USD/oz**, NOT INR/g. |
| **Live WebSocket (`bcrate_Type == 5`)** | `ws://www.kjpl.in/ws` (subprotocol `SOCKET_TOKEN`) | Streams pipe-delimited snapshots (`1\|G`, `1\|S`, `1\|I`, `2\|GOLD`, `2\|SILVER`, `3\|47..52`, `4\|4\|<rate_display>\|<market_status>\|<msg>`). Observed live movement (`14522.80` -> `14517.00` for ID 47). |
| **Live Text Snapshot** | `http://www.kjpl.in/client/kjpl.txt` | Tab-delimited current snapshot with full timestamp row (`4\t4\t-\t1\t0\t\t"11/11/2026 02:01:59 PM"`), Type 1 (`SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR`), Type 2 (`GOLDDEC`, `SILVERDEC`), Type 3 (`47..52`). |
| **Inline JS Config & Bank Costing** | `<script>` inline vars (`rpaneldata`, `rpanelbankrates`, `rpanelcommodities`, `rpanelcontract`) | `rpaneldata.lastupdatetime` (`11-11-2026 12:36:22`), `rpaneldata.market_status` (`0`), `rpanelbankrates` (`custom`, `btax_value`, `premium`, `bconvert_value`), `rpanelcommodities` (`comid`, `selldiff`, `buydiff`, `sellrate`). |
| **Live `#liveratetable` Hidden Divs** | `#liveratetable tr.ratelive td:last div` | Product IDs `47`–`52` all carry `com_weight: 1.000`, `sell_rate: 145223.00` (10g basis), `sell_diff: 3350.00`; WS/txt emits `47=14517.00` (`com_sel_premium=17`) and `48..52=14500.00` (**1g INR basis**, NOT 100g/1kg totals as fixture assumed). |

> **Unresolved / Unverified Semantics Flagged for Phase 1:** `com_display_purity` (`0.00` on ID 47 vs `100.00` on IDs 48–52), `com_bar_quantity` (`500`), red/green visual highlight vs bid/ask polarity (`td:eq(1)`/`td:eq(2)` show `buying_rate`/`selling_rate` per `booking.js`, green on tick up, red on tick down — NOT bid/ask!), and whether `GOLD 100 GMS 999` IDs 48–52 differ by city during active sessions or mirror Chennai's base calculation. Also note `.com_tax`, `.com_octroi`, `.com_stamduty` in `#liveratetable` are empty in default HTML.

---

## Detailed Defect Inventory by Category

### 1. Critical Data-Integrity Defects

| ID | Defect | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **DI-1** | **Non-KJPL data providers active (`yfinance`)** | `scripts/collect_market_csv.py`, `backend/app/services/market/client.py`, `collector.py`, `data_service.py` (L290), `bullion_service.py` (L301), `.github/workflows/market-collector.yml` | Legacy COMEX/FX ingestion used Yahoo Finance instead of KJPL's native Type 1 (`SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR`), Type 2 (`GOLDDEC`, `SILVERDEC`), and LBMA feeds. | Violates exclusive KJPL data-source rule; introduces external price divergence. | Remove `yfinance` from runtime/collectors; ingest international/MCX benchmarks strictly from KJPL (`ws://www.kjpl.in/ws` / `kjpl.txt` / LBMA table) or mark unavailable. | **Resolved (Verified)** |
| **DI-2** | **15 corrupt historical rows in `city_rates.csv`** | `data/kjpl/city_rates.csv`, `backend/app/services/kjpl/city_parser.py` (L295-334) | Table fallback scanned all `<tr>` elements without excluding LBMA USD/oz (`Table 9/13`) or combined header (`Table 0`), and picked `valid_numbers[-1]` across concatenated hidden `<div>` metadata, extracting `200/210` (silver), `4043.65` & `50.1–52.82` (USD/oz), `100.0` (`com_display_purity`), `51.0`/`52.0` (`com_id`). | Presented ₹100 / ₹51 as 100g gold rates (~ -99% fake drops) and USD/oz as INR/g rates. | Quarantine all 15 corrupt rows via remediation migration/script (`QUARANTINED`); rewrite parser to reject mixed-unit HTML tables and read strict KJPL JSON/WS/`kjpl.txt` + exact table selectors. | **Resolved (Verified)** |
| **DI-3** | **99 duplicate Oct 31 rows & test-polluted CSV/DB** | `data/kjpl/city_rates.csv` (9×11 rows on `2026-10-31`), `data/goldsense.db` (`2026-11-10` fixture rows), `backend/tests/test_kjpl_city_extraction.py` (L88-108) | `test_persistence_unchanged_price_detection` deleted real `data/goldsense.db` tables and wrote fixture `13085000.0` payloads into real `CITY_RATES_CSV`. | Real DB and CSV polluted every `pytest` run; artificial duplicates on Oct 31. | Isolate all tests with temporary SQLite DBs and `tmp_path` CSV overrides; quarantine/deduplicate Oct 31 CSV duplicates and clean `goldsense.db`. | **Resolved (Verified)** |
| **DI-4** | **6 duplicate early rows in `kjpl_rates.csv`** | `data/kjpl/kjpl_rates.csv` (Sep 19–24, 2026) | Early collector runs lacked date+published_time deduplication, causing 2× entries for Sep 19–24. | Inflates raw count (53 raw vs 47 unique events). | Quarantine duplicate rows cleanly in audit log while keeping raw traceability. | **Resolved (Verified)** |
| **DI-5** | **Weight/Unit mismatch between `city_parser.py` & live KJPL** | `backend/app/services/kjpl/city_parser.py` (L26-115), `bullion_service.py` (L99-101, 158-159) | `KNOWN_COM_ID_MAP` sets `weight=100.0, unit='100g'` for IDs `48..52`, and `bullion_service.py` divides `price / weight`. Live KJPL `kjpl.txt` & WS emit **`14500.00` (1g rate)**! | Dividing live `14500.00` by `100.0` would report **₹145.00/g** (100× undervaluation)! | Inspect and lock exact unit basis from `com_weight` & live feed (`14500.00` = per 1g) before enabling live DB writes; enforce strict product-specific INR/g bounds (`[5000, 50000]`). | **Resolved (Verified)** |
| **DI-6** | **Silver missing fallback hardcoded `220.0`** | `backend/app/services/data_service.py` (L143), `portfolio_service.py` (L21-22) | Hardcoded `220.0` / `13135.0` fallback when KJPL silver/CSV is absent. | Violates zero-fabrication rule (masks missing values with invented constants). | Return `None` / explicit unavailable state instead of hardcoded rates. | **Resolved (Verified)** |
| **DI-7** | **Time-only string parsing loses source date** | `backend/app/services/kjpl/parser.py` (L22-65), `city_parser.py` (L129-149) | Parses `.mjdma_data` (`Time : 09:35 am`) combined with `datetime.now(IST)` date, ignoring `UPDATED: 11-11-2026 09:37:32 am` in `.chennairate_table`. | On weekends/holidays (e.g., Sunday), stamps Friday/Saturday's MJDTA rate with today's date, making stale data look fresh. | Parse full date+time directly from Table 10/14 `UPDATED:` cell (`%d-%m-%Y %I:%M:%S %p`) and `kjpl.txt` Type 4 timestamp (`11/11/2026 02:01:59 PM`). | **Resolved (Verified)** |

### 2. Backend Architecture Defects

| ID | Defect | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **BA-1** | **Duplicate writers (APScheduler inside FastAPI)** | `backend/app/main.py` (L13, L25-33), `backend/app/jobs/scheduler.py`, `jobs/pipeline_job.py` | FastAPI `lifespan` starts `BackgroundScheduler` running KJPL & Yahoo collectors every hour inside the API server process, duplicating external collectors. | Race conditions, duplicate observations, Yahoo Finance runs inside API process. | Remove APScheduler startup from `main.py`; enforce single-writer per pipeline (GitHub Actions for MJDTA, dedicated Oracle worker for live KJPL). | **Resolved (Verified)** |
| **BA-2** | **Silent fallback to stale CSV/SQLite in API** | `backend/app/services/bullion_service.py` (L76-81, 187-199, 376-410), `data_service.py`, `api/routes/kjpl.py`, `market.py` | `except Exception: pass` catches DB errors and falls back to `data/kjpl/city_rates.csv` or `kjpl_rates.csv`. | Hides Neon PostgreSQL outages and serves stale repo CSV rates as if live. | Fail explicitly with `503` / `DEGRADED` database-unavailable payload in production; remove silent CSV fallbacks on live endpoints. | **Resolved (Verified)** |
| **BA-3** | **Excessive sequential DB connections per request** | `backend/app/services/bullion_service.py`, `api/routes/bullion.py` | Each helper opens/closes separate `SessionLocal()` sessions; `get_data_monitor_status()` opens 3 separate DB queries/connections per call. | High latency on Neon scale-to-zero / pooler and connection churn. | Use FastAPI dependency-injected `Session` (`Depends(get_db)`) with bounded pool and consolidated `/api/bullion/dashboard` endpoint. | **Resolved (Verified)** |
| **BA-4** | **Hardcoded outdated import duty assumptions** | `backend/app/services/bullion_service.py` (L306-308) | Hardcodes `customs_duty_pct = 0.06`, `cess_pct = 0.01`, `gst_pct = 0.03` on top of Yahoo `GC=F` & `USDINR=X`. | Violates KJPL-only rule and uses unverified duty percentages as fact. | Remove external Yahoo parity math; surface verified KJPL Spot USD + FX parity cleanly without hardcoded duty assumptions. | **Resolved (Verified)** |

### 3. Database and Persistence Defects

| ID | Defect | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **DB-1** | **Supabase/Render lock-in in `session.py` & scripts** | `backend/app/db/session.py` (L35-44), `scripts/verify_supabase_connection.py`, `.github/workflows/kjpl-collector.yml` (L52) | Targets `SUPABASE_DATABASE_URL`, `RENDER` env check, and lacks Neon SSL/timeout/pooling configuration (`pool_size`, `max_overflow`, `NullPool` for collectors). | Fails to strictly enforce Neon PostgreSQL in Oracle/serverless deployments. | Configure Neon PostgreSQL (`DATABASE_URL` with `sslmode=require`, `connect_timeout`), bounded `QueuePool` for FastAPI, `NullPool` for short-lived collectors. Keep existing Supabase project/secret untouched for manual approval. | **Resolved in Code (Live Neon Secret Pending)** |
| **DB-2** | **Monetary fields use `Float` instead of `Numeric`/`Decimal`** | `backend/app/models/bullion.py`, `gold_rate.py`, `market_rate.py`, `portfolio.py`, `alert.py` | SQLAlchemy `Float` maps to IEEE-754 double precision. | Floating-point precision drift in price diffs, valuations, and equality checks (`abs(a - b) > 0.001`). | Migrate monetary columns to `Numeric(14, 2)` / `Numeric(14, 4)` with `Decimal` arithmetic via Alembic migration `a7c3e91b42d0`. | **Resolved (Verified)** |
| **DB-3** | **No `validation_status` / quarantine columns in DB** | `backend/app/models/bullion.py`, `backend/migrations/versions/0f1a9481a06e_*.py` | `BullionRateObservation` only has `is_changed` and `freshness_status`, lacking `validation_status` (`VALID`, `SUSPECT`, `QUARANTINED`, `INVALIDATED`), `quarantine_reason`, `product_weight_grams`, `normalized_price_per_gram`, or raw payload audit fields. | Corrupt rows cannot be quarantined safely without deletion. | Add quarantine/validation/audit columns via Alembic migration `a7c3e91b42d0` and backfill historical remediation. | **Resolved (Verified)** |
| **DB-4** | **Models import order & missing `init_database` in migrations** | `backend/app/db/session.py`, `migrations/env.py` | Production startup calls `create_all()` instead of strict Alembic migration control. | Schema drift risk between SQLAlchemy models and Neon. | Enforce Alembic migrations as single source of truth for schema evolution in PostgreSQL. | **Resolved (Fresh SQLite Verified; Live Neon Pending)** |

### 4. KJPL Extraction Defects

| ID | Defect | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **EX-1** | **`city_parser.py` misses actual live KJPL endpoints** | `backend/app/services/kjpl/city_parser.py` | Only scrapes initial HTML response via BeautifulSoup instead of `ws://www.kjpl.in/ws`, `http://www.kjpl.in/client/kjpl.txt`, `rpaneldata`, and `rpanelbankrates`. | Static HTML `#liveratetable` sell-rate column is `-` or blank until JS hydrates; Strategy A regex matches zero scripts (`comid` vs `com_id`). | Implement dedicated Pipeline A (MJDTA HTML Table 10/11 + full timestamp) and Pipeline B (Oracle continuous WebSocket `ws://www.kjpl.in/ws` + `kjpl.txt` parser). | **Resolved (Verified Live)** |
| **EX-2** | **Table parser parses LBMA ($) & weight (`100.0`) as prices** | `backend/app/services/kjpl/city_parser.py` (L294-334) | `is_bullion_row` matches any `<tr>` containing `GOLD`/`SILVER` and grabs `valid_numbers[-1]`. | Confuses USD/oz LBMA fix with INR/g MJDTA and `com_display_purity`/`com_id` with INR city prices. | Restrict HTML parsing to explicit targeted tables/selectors (`.chennairate_table` headers verified) and discard generic brute-force `<tr>` scanning. | **Resolved (Verified)** |

### 5. Deployment and Hosting Defects

| ID | Defect | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **DP-1** | **GitHub Actions commits data into `develop` as a DB** | `.github/workflows/kjpl-collector.yml`, `market-collector.yml`, `news-collector.yml`, `pipeline-update.yml` | Workflows commit CSVs back to `develop` repeatedly (100+ automated data commits, rebase conflicts, repository bloat). | Violates clean source-control separation; Git is used as primary DB; blocks continuous live updates. | Configure GitHub Actions exclusively for scheduled Pipeline A (MJDTA -> Neon DB directly), remove automated commits to `develop`, and move continuous live KJPL to Oracle VM + systemd. | **Resolved in Config (Oracle/Neon Pending)** |
| **DP-2** | **Empty `docker-compose.yml` & bloated `requirements.txt`** | `docker-compose.yml` (0 bytes), `backend/requirements.txt` (51 packages incl. `xgboost`, `scipy`, `pandas`, `yfinance`, `apscheduler`) | All ML/dev/collector packages bundled together; `docker-compose.yml` is empty. | Heavy production API footprint unsuitable for Oracle Always Free VM memory limits (1 GB RAM on AMD micro / 24 GB ARM if available). | Split `requirements-api.txt`, `requirements-worker.txt`, `requirements-ml.txt`; remove `yfinance`; populate `docker-compose.yml` + `deploy/oracle/*`. | **Resolved (Created)** |

### 6. Security Vulnerabilities

| ID | Vulnerability | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **SEC-1** | **CORS wildcard with `allow_credentials=True`** | `backend/app/main.py` (L44-50) | `allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"]` with `allow_credentials=True`. | Invalid/insecure CORS policy allowing arbitrary cross-origin requests in browser contexts. | Restrict `allow_origins` to explicit env-configured origins (`ALLOWED_ORIGINS`) without `"*"`. | **Resolved (Verified)** |
| **SEC-2** | **Auth disabled by default + shared single key (`DEFAULT_USER`) + `X-User-ID` header trust in dev** | `backend/app/core/auth.py` (L11-76) | `AUTH_ENABLED` defaults to `false`; in disabled mode trusts arbitrary `X-User-ID`; in enabled mode maps single `GOLDSENSE_API_KEY` to `"owner"`. | No real multi-user authentication; multi-tenant vault cannot safely ship without proper per-user JWT/session auth or explicit single-user lock. | Enforce explicit `ALLOW_TEST_USER_HEADER=true` opt-in for non-auth `X-User-ID` switching and require Bearer/API-key when `AUTH_ENABLED=true`. | **Resolved (Verified)** |
| **SEC-3** | **Unauthenticated destructive/trigger endpoints** | `backend/app/api/routes/market.py` (`/refresh` GET/POST) | `GET/POST /api/market/refresh` triggers external fetch without authentication (only 60s global cooldown). | Allows external callers to trigger outbound collector work. | Decommission external Yahoo refresh path; `/refresh` serves persisted state safely. | **Resolved (Verified)** |
| **SEC-4** | **Upstream KJPL `SOCKET_TOKEN` / raw secrets management** | `.github/workflows/kjpl-collector.yml` (`SUPABASE_DATABASE_URL`) | Existing GitHub Secret references Supabase; env vars lack validation on startup in non-Render clouds (Oracle). | Production startup silently falls back to SQLite on Oracle if `ENVIRONMENT=production` without `RENDER=1`! (`session.py` L35 checks `os.environ.get("RENDER")`!). | Fail closed in `ENVIRONMENT=production` on ANY host; rotate workflows to `NEON_DATABASE_URL` and retain `SUPABASE_DATABASE_URL` pending user removal approval. | **Resolved in Code (Secret Cutover Pending User)** |

### 7. Frontend / API Integration Defects

| ID | Defect | Exact Files | Root Cause | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|---|
| **FE-1** | **Relative `/api/...` paths with no rewrite or `NEXT_PUBLIC_API_BASE_URL`** | `frontend/app/page.tsx`, `frontend/lib/api.ts`, `frontend/next.config.ts` | Next.js on Vercel calls `/api/bullion/latest` on the Vercel domain instead of the Oracle FastAPI backend. | **All API calls return 404 on Vercel deployment.** | Centralize API client using `NEXT_PUBLIC_API_BASE_URL` (and Next.js dev proxy rewrites). | **Resolved (Build Verified)** |
| **FE-2** | **2,378-line monolithic `page.tsx` with 11+ parallel fetches** | `frontend/app/page.tsx`, `frontend/components/bullion/KjplLiveDeskPanel.tsx` | Single client component handles state, 11 initial fetch calls, modals, charts, parity, portfolio, alerts, news, and data monitor. | Heavy re-renders, waterfall latency, difficult maintenance, no WebSocket/SSE live stream. | Extracted `KjplLiveDeskPanel.tsx`, consolidated initial fetches to `/api/bullion/dashboard`, and wired SSE `/api/bullion/stream` updates. *(Further component extraction remains optional future refactoring.)* | **Partially Resolved (Core Consolidated + Live Desk Extracted)** |

### 8. Documentation Inconsistencies

| ID | Inconsistency | Exact Files | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|
| **DOC-1** | Outdated Supabase + Render + Yahoo Finance architecture documented everywhere | `README.md`, `CLAUDE.md`, `HANDOFF_TO_CLAUDE.md`, `AGENTS.md`, `docs/architecture/*`, `docs/data/*`, `docs/operations/*` | Misleads engineers/agents about active data sources and hosting stack. | Update all active docs to reflect KJPL-only + Oracle + Neon + Vercel + GitHub Actions (MJDTA); mark historical decisions superseded via `ADR-001`. | **Resolved (Verified)** |

### 9. Testing Gaps

| ID | Gap | Exact Files | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|
| **TST-1** | Tests mutate real DB & real CSVs | `backend/tests/test_kjpl_city_extraction.py` | Pollutes local `goldsense.db` and `city_rates.csv` on every test run. | Isolate all persistence tests to `tmp_path` + in-memory/temp SQLite. | **Resolved (Verified)** |
| **TST-2** | Fixture vs live site divergence | `backend/tests/fixtures/kjpl/kjpl_live_sample.html` | Fixture includes `<script id="commodity-data">` and `1308500.00` rows that do not exist on live `kjpl.in`; hides live `kjpl.txt` / WS contract bugs. | Added live `kjpl.txt`/WS contract tests alongside corruption regression tests (`₹200`, `4043.65`, `51.99`, `100.0`). | **Resolved (Verified)** |
| **TST-3** | Frontend & API integration coverage | `frontend/`, `backend/tests/test_bullion_api.py` | Verify frontend lint/build and add `/health` 503, Neon URL SSL, fail-closed prod, and SSE tests. | Added Neon/DB-503/SSE backend tests and verified `npm run lint && npm run build`. | **Resolved (Verified)** |

### 10. Performance and Scalability Concerns

| ID | Concern | Exact Files | Consequence | Recommended Correction | Status |
|---|---|---|---|---|---|
| **PS-1** | Zero caching / `NullPool` missing for collectors / heavy pandas load | `backend/app/services/bullion_service.py`, `data_service.py`, `requirements*.txt` | Re-parsing CSV files and opening multi-connections per request; Neon cold-start latency unbuffered. | Single injected DB session (`Depends(get_db)`), `NullPool` for collectors, bounded `QueuePool` for FastAPI, split `requirements*.txt`, consolidated dashboard + SSE push. | **Resolved (Verified)** |

---

## Phased Implementation Roadmap

1. **Phase 1 — Data Contracts & KJPL Verification:** Verify all `kjpl.txt`, WebSocket (`ws://www.kjpl.in/ws`), `rpanel*`, LBMA, and MJDTA field semantics/units (`booking.js` conversion trace), document verified KJPL Data Dictionary (`docs/data/KJPL_DATA_DICTIONARY.md`).
2. **Phase 2 — Data Corruption Remediation:** Quarantine all 15 corrupt rows + 99 Oct 31 duplicates in `city_rates.csv` and duplicates in `kjpl_rates.csv`, fix `test_kjpl_city_extraction.py` test isolation, rebuild strict validator + parser, generate remediation report.
3. **Phase 3 — Neon Database & Precision Upgrade:** Replace Supabase/Render coupling with Neon PostgreSQL config, upgrade monetary fields to `Numeric(14, 2)` + quarantine/validation columns via Alembic migration, fail closed on DB absence in production.
4. **Phase 4 — Dual-Pipeline Collector & Single-Writer Control:** Remove APScheduler from FastAPI and remove Yahoo Finance (`yfinance`) completely. Implement Pipeline A (GitHub Actions -> Neon MJDTA, no git commits) and Pipeline B (continuous Oracle KJPL WebSocket/txt worker + systemd unit).
5. **Phase 5 — Backend & Real-Time Streaming API:** Consolidate `/api/bullion/dashboard`, add SSE/WebSocket genuine-tick streaming, strict timestamps/freshness per feed cadence, CORS + auth hardening.
6. **Phase 6 — Frontend Integration:** Fix API base URL routing (`NEXT_PUBLIC_API_BASE_URL`), modularize `page.tsx`, connect SSE/streaming updates, display honest freshness/timestamps/quarantine-free city matrix.
7. **Phase 7 — ₹0/Month Deployment Prep & Dependency Split:** Split `requirements*.txt`, Docker/systemd deployment configs for Oracle + Neon + Vercel.
8. **Phase 8 — Documentation & Verification:** Update all `.md` files + ADR, run full regression/integration/build tests, verify end-to-end.
