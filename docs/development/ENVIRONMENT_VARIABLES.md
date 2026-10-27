# Environment Variables Configuration

Copy `backend/.env.example` to `backend/.env` for local configuration.

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://user:pass@localhost:5432/goldsense` | Primary PostgreSQL database connection string. If connection fails, system falls back to `sqlite:///data/goldsense.db`. |
| `ENVIRONMENT` | `development` | Deployment environment (`development`, `staging`, `production`). |
| `LOG_LEVEL` | `INFO` | Application log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated list of allowed CORS client origins. |
| `CACHE_DEBOUNCE_SECONDS` | `60` | Cooldown period between manual rate refresh triggers. |
| `AUTH_ENABLED` | `false` | When true, enforces server-side authorization on portfolio & alerts APIs. |
| `GOLDSENSE_API_KEY` | `""` | Secret key used for Bearer token or X-API-Key validation when auth is enabled. |
| `NEWS_LOOKBACK_HOURS` | `6` | Hours of backward window for RSS news ingestion crons. |
