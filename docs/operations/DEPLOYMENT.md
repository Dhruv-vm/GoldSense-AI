# Deployment Guide

## 1. Production Architecture
In production, GoldSense AI is deployed using containerized services or cloud virtual machines (e.g., Docker, AWS ECS, Google Cloud Run).

- **Frontend**: Next.js deployed on Vercel, AWS Amplify, or a standalone Node.js container.
- **Backend**: FastAPI served via `uvicorn` behind a reverse proxy (e.g. NGINX, Traefik, or Caddy) with SSL termination.
- **Database**: Managed PostgreSQL instance (e.g. AWS RDS, Supabase, Neon) with connection pooling.

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
