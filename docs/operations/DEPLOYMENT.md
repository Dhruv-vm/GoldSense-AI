# Deployment Guide (₹0/Month Target Stack — ADR-001)

## 1. Production Architecture
VMD Bullion runs on a zero-cost production architecture (superseding Render + Supabase):

- **Frontend (Vercel Hobby)**: Next.js 16 deployed on Vercel Hobby with `NEXT_PUBLIC_API_BASE_URL` pointing to the Oracle API origin (`https://api.<domain>`).
- **Backend API & Live Worker (Oracle Cloud Always Free VM)**:
  - `deploy/oracle/vmd-bullion-api.service`: `uvicorn app.main:app` using `backend/requirements-api.txt` with bounded SQLAlchemy queue pool (`DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`, **no** APScheduler).
  - `deploy/oracle/vmd-kjpl-worker.service`: Continuous single-writer Pipeline B worker (`scripts/kjpl_live_worker.py`) using `backend/requirements-worker.txt` with `fcntl` host lock.
  - `deploy/oracle/nginx-vmd-bullion.conf`: Nginx TLS reverse proxy with `proxy_buffering off` / `X-Accel-Buffering: no` for SSE (`/api/bullion/stream`).
- **Database (Neon PostgreSQL Free Tier)**: Managed serverless PostgreSQL (`sslmode=require`, Alembic revision `9b4e1d8c3a02`). Apply [`deploy/neon/roles_and_grants.sql`](../../deploy/neon/roles_and_grants.sql) once as DBA to provision distinct `vmd_migrator`, `vmd_app_runtime`, and `vmd_research_readonly` roles. Migrations run via `.github/workflows/db-migrate.yml` using `NEON_MIGRATION_DATABASE_URL`, while Oracle API/worker and GitHub collector jobs use `NEON_RUNTIME_DATABASE_URL` (`vmd_app_runtime`). Startup fails closed in `ENVIRONMENT=production` if `DATABASE_URL` is missing, SQLite, or unreachable.
- **Scheduled MJDTA Collector**: GitHub Actions (`.github/workflows/kjpl-collector.yml`) writing directly to `NEON_RUNTIME_DATABASE_URL` (`DB_USE_NULLPOOL=true`).

---

## 2. Docker Compose (Local Production Parity) & Split Requirements

Three dependency profiles minimize cloud memory usage:
- `backend/requirements-api.txt` — FastAPI + Uvicorn + SQLAlchemy + psycopg3 (API runtime)
- `backend/requirements-worker.txt` — WebSockets + BeautifulSoup + psycopg3 (Oracle live collector)
- `backend/requirements-ml.txt` — PyTorch / FinBERT / scikit-learn (offline CI ML pipeline only)

See `docker-compose.yml` and `.env.example` at the repository root for containerized local parity.

---

## 2. Docker Deployment

### Backend Dockerfile Example
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/backend/
COPY data/ /app/data/
ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Frontend Dockerfile Example
```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:18-alpine AS runner
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "start"]
```
