# Environment Variables Configuration

Copy `.env.example` (at repo root) to `.env` for local configuration.

| Variable | Default / Example | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://vmd_app_runtime:...@ep-host.neon.tech/neondb?sslmode=require` | Runtime Neon PostgreSQL URI using the restricted `vmd_app_runtime` role (auto-normalized to `postgresql+psycopg://` with `sslmode=require`). In `ENVIRONMENT=production`, startup **fails closed** if unset, SQLite, or unreachable. Local dev/tests fall back to SQLite `data/goldsense.db`. |
| `MIGRATION_DATABASE_URL` | `postgresql://vmd_migrator:...@ep-host.neon.tech/neondb?sslmode=require` | Dedicated DDL/migration owner URI (`vmd_migrator`) used exclusively by `alembic upgrade head` (`.github/workflows/db-migrate.yml`), kept strictly separate from runtime `DATABASE_URL`. |
| `READONLY_DATABASE_URL` | `postgresql://vmd_research_readonly:...@ep-host.neon.tech/neondb?sslmode=require` | Optional `SELECT`-only URI (`vmd_research_readonly`) for offline reporting and diagnostics. |
| `DB_USE_NULLPOOL` | `false` (`true` in GitHub Actions) | Use SQLAlchemy `NullPool` for short-lived CLI/Actions collector jobs instead of bounded API queue pool. |
| `ENVIRONMENT` | `development` | Deployment environment (`development`, `staging`, `production`). |
| `ALLOWED_ORIGINS` | `http://localhost:3000,https://vmd-bullion.vercel.app` | Comma-separated explicit CORS origins (wildcards with credentials prohibited). |
| `AUTH_ENABLED` | `false` | When `true`, requires `Authorization: Bearer <token>` or `X-API-Key` on portfolio & alerts APIs. |
| `ALLOW_TEST_USER_HEADER` | `false` | Must remain `false` in production; only tests/local debug may enable `X-User-ID` override when `AUTH_ENABLED=false`. |
| `VMD_API_KEY` / `GOLDSENSE_API_KEY` | `""` | API key / Bearer token secret when `AUTH_ENABLED=true`. |
| `ENABLE_CSV_MIRROR` | `true` (`false` in cloud collectors) | Controls optional local CSV mirroring during persistence. |
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.<domain>` (Vercel) | Explicit backend API origin used by Next.js client requests & EventSource SSE. |
| `NEWS_LOOKBACK_HOURS` | `6` | Hours of backward window for RSS/GDELT news ingestion crons. |
