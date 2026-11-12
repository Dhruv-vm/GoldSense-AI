# ADR-001: KJPL-Exclusive Ingestion, Oracle Always Free + Neon + Vercel Architecture, and Monetary Precision

- **Status:** Accepted (2026-11-11)
- **Branch:** `develop`
- **Supersedes:** Earlier prototype decisions documented in `HANDOFF_TO_CLAUDE.md`, legacy `SYSTEM_ARCHITECTURE.md`, and early `CLAUDE.md` revisions that used Yahoo Finance (`yfinance`), Supabase PostgreSQL, Render hosting, APScheduler inside FastAPI, and automated GitHub Actions CSV commits to `develop`.

---

## 1. Context

An end-to-end engineering and data-integrity audit (`docs/VMD_BULLION_MASTER_AUDIT.md`) identified critical defects in the prototype GoldSense AI stack:
1. **Non-KJPL Upstream Data (`yfinance`)**: Using Yahoo Finance (`GC=F`, `SI=F`, `USDINR=X`) violated the core mandate that KJPL is the exclusive bullion and FX upstream source, while KJPL itself directly publishes `SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR`, LBMA AM/PM fixes, MJDTA references, and city/bar physical rates.
2. **Database & Hosting Stack (`Render` + `Supabase`)**: Render free web services sleep after 15 minutes of inactivity and fail to run continuous WebSocket collectors; `Float` columns introduced binary rounding drift; production fallback checked only `RENDER=1`, silently falling back to local SQLite on other Linux hosts.
3. **Dual/Contending Writers & Git Churn**: APScheduler ran inside FastAPI simultaneously with GitHub Actions crons that committed CSV files back into `develop`.
4. **Historical Data Contamination**: `data/kjpl/city_rates.csv` and `kjpl_rates.csv` contained unquarantined unit/column-shift corruptions (`₹100` weight artifacts, `₹51`/`₹52` `com_id`/USD-oz silver contamination, `4043.65` LBMA gold USD/oz rows under INR columns, and 99 October 31 duplicates).

---

## 2. Decisions

1. **KJPL-Exclusive Bullion & FX Source**
   - Permanently decommissioned `yfinance` / Yahoo Finance collectors (`scripts/collect_market_csv.py`, `backend/app/services/market/client.py`, `.github/workflows/market-collector.yml`).
   - All spot USD metals, USD/INR (`Type 1`: `SPOT-GOLD`, `SPOT-SILVER`, `SPOT-INR`), Indian contracts (`Type 2`: `GOLDDEC`, `SILVERDEC`), 5-city + 1KG bar physical cash rates (`Type 3`: `47`–`52`), LBMA fixes, and MJDTA reference prices are sourced strictly from KJPL.
   - Missing KJPL values must remain unavailable (`None` / `SOURCE_UNAVAILABLE`); never fabricated or substituted.

2. **₹0/Month Target Infrastructure**
   - **Frontend:** Vercel Hobby (`Next.js 16` app routing cross-origin API & SSE requests via `NEXT_PUBLIC_API_BASE_URL`).
   - **Backend API & Continuous Live Worker:** Oracle Cloud Always Free Compute VM running:
     - `vmd-bullion-api.service`: `uvicorn app.main:app` (single API process, bounded SQLAlchemy queue pool, **no** APScheduler).
     - `vmd-kjpl-worker.service`: continuous single-writer Pipeline B worker consuming `ws://www.kjpl.in/ws` (`SOCKET_TOKEN` subprotocol) + `http://www.kjpl.in/client/kjpl.txt` with `fcntl` host lock (`scripts/kjpl_live_worker.py`).
     - Reverse proxy via Nginx (`deploy/oracle/nginx-vmd-bullion.conf`) with SSE buffering disabled (`X-Accel-Buffering: no`) on `/api/bullion/stream`.
   - **Database:** Neon PostgreSQL Free Tier (`sslmode=require`, `postgresql+psycopg://`, Alembic schema at `a7c3e91b42d0`). Short-lived GitHub Actions jobs use `DB_USE_NULLPOOL=true`. Startup in `ENVIRONMENT=production` fails closed if `DATABASE_URL` is absent, SQLite, or unreachable.
   - **Scheduled MJDTA Collector (Pipeline A):** `.github/workflows/kjpl-collector.yml` executes twice-daily IST MJDTA HTML extraction directly into Neon (`NEON_DATABASE_URL`) without committing CSV mutations to `develop`.

3. **Monetary Decimal Precision & Audit Quarantine**
   - All monetary/price columns use PostgreSQL `NUMERIC(14, 2)` / `NUMERIC(14, 4)` (`Numeric`), avoiding IEEE-754 float drift.
   - Ambiguous/corrupt observations are preserved and flagged (`QUARANTINED` + `quarantine_reason` in DB and `data/kjpl/quarantined_*.csv`) rather than silently deleted.

---

## 3. Consequences & Operational Actions

- Historical docs mentioning Supabase, Render, or `yfinance` are marked superseded and updated to reference Neon, Oracle Always Free, Vercel, and KJPL-exclusive feeds.
- **GitHub Secret Cleanup (Pending User Approval):** Previously configured `SUPABASE_DATABASE_URL` in GitHub Repository Secrets is superseded by `NEON_DATABASE_URL`. Do **not** remove `SUPABASE_DATABASE_URL` or delete the external Supabase project until the user approves after verifying live Neon ingestion.
