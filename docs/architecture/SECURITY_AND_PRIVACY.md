# Security, Privacy & Multi-User Isolation

## 1. Multi-Tenant User Isolation
Personal bullion holdings and net worth data represent highly sensitive personal financial information. GoldSense AI enforces multi-user isolation by design:
- Every record in `portfolio_holdings` and `alert_rules` requires an indexed `user_id`.
- The API extracts the caller's tenant identifier via standard authentication middleware or the `X-User-ID` header.
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
