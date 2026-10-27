# Security, Privacy & Multi-User Isolation

## 1. Multi-Tenant User Isolation & Server-Side Authorization
Personal bullion holdings and net worth data represent highly sensitive personal financial information. GoldSense AI enforces server-side authorization:
- `app.core.auth.get_current_user`: Server-side dependency that extracts and validates identity.
- In production / authenticated environments (`AUTH_ENABLED=true`):
  - Requires `Authorization: Bearer <token>` or `X-API-Key`.
  - The server verifies the secret token against `GOLDSENSE_API_KEY` using constant-time comparison (`secrets.compare_digest`).
  - Unauthenticated requests or invalid tokens are rejected with `HTTP 401 Unauthorized` or `HTTP 403 Forbidden`.
  - The static API key binds authorization strictly to the designated vault owner (`owner`). Callers cannot supply an arbitrary `X-User-ID` to access other user partitions (rejected with `HTTP 403 Forbidden`).
  - *Note on future multi-user access*: A static shared API key is not a user-specific identity provider. When public multi-user access is enabled in Phase 3, cryptographic JWTs with signed user identity claims (`sub`) will replace static service keys.
- In single-user personal mode (`AUTH_ENABLED=false`):
  - Operates as a local personal vault bound to `owner` by default.
- Every record in `portfolio_holdings` and `alert_rules` requires an indexed `user_id`.
- Cross-user queries are prevented at the database service layer (e.g., `filter(PortfolioHolding.user_id == user_id)` is applied to all CRUD queries).
- A user cannot read, update, or delete another user's holdings; attempts return `HTTP 404 Not Found`.

---

## 2. Shared vs. Private Boundaries
- **Shared Assets (Public Read)**:
  - KJPL Spot Rates (`data/kjpl/kjpl_rates.csv`)
  - Yahoo Finance Market Data (`data/market/market_rates.csv`)
  - Aggregated Financial News & Sentiment (`data/news/news_articles.csv`, `ml/data/processed/analyzed_news.csv`)
  - Machine Learning Training Weights & Forecasts
- **Private Assets (Tenant Restricted)**:
  - Physical Bullion Holdings (quantities, purchase prices, purities)
  - Portfolio Valuations and Unrealized Gains/Losses
  - Alert configurations and trigger histories

---

## 3. Environment Protection
- Secrets such as API keys and database credentials are kept out of source control via `.gitignore`.
- `.env.example` provides non-sensitive defaults for local development.
