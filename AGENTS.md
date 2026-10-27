# AGENTS.md — Agent & Developer Engineering Guidelines

This document establishes the binding engineering principles, operational invariants, and architectural standards for AI agents and human developers contributing to **GoldSense AI**.

---

## 1. Prime Directives

1. **Absolute Data Integrity & Zero Fabrication**
   - Never fabricate data, synthesize artificial historical prices, or modify prediction targets/features to inflate model performance metrics.
   - If historical data contains gaps, holidays, or missing returns, document them transparently or handle them via forward-filling/masking. Never invent values.
   - When sample counts are below statistical viability thresholds (e.g., $N < 50$ events for ML training), explicitly label the state as `EXPERIMENTAL_DATA_COLLECTION` in the UI and API.

2. **Zero Lookahead Bias & Point-in-Time Discipline**
   - All machine learning features generated at time $t$ for predicting price at $t + \Delta$ must use strictly information available on or before $t$.
   - Any news sentiment aggregation must enforce an explicit cutoff: $\text{article\_published\_at} \le t$. Articles published after market close or event timestamp must never leak into that day's feature vector.
   - Shifted targets (`next_event_gold`) must be computed by strictly shifting backwards in time relative to feature rows.

3. **No Commercial Selling Workflows**
   - GoldSense AI is a **personal bullion tracking and market intelligence platform**, not an e-commerce or retail jeweler management software.
   - **Forbidden features**: Point-of-Sale (POS), shopping carts, checkout, merchant payments, customer management (CRM), supplier accounts, sales invoicing, GST commercial billing, stock dispatch, or shipping tracking.
   - Allowed features: Personal bullion holdings management (gold & silver, weight in grams/kg, purity, acquisition cost, market valuation, unrealized gain/loss).

4. **Multi-User Isolation & Personal Privacy**
   - All portfolio holdings, custom alert rules, and user-specific preferences must carry an explicit `user_id`.
   - APIs must enforce tenancy/user isolation via authenticated sessions or the `X-User-ID` header.
   - Market rate data, news sentiment, and machine learning models are shared system assets; personal portfolio records are strictly private.

5. **Non-Destructive Operations & Git Hygiene**
   - All active development must take place on the `develop` branch.
   - **Never run `git push --force`** or rewrite remote branch history.
   - Do not overwrite valid historical rate records in `data/kjpl/` or `data/market/`. Data collection must be strictly additive and append-only.

---

## 2. Technical Standards & Domain Invariants

### Precious Metals Conversion Math
Always adhere to standardized metallurgical and financial constants:
- **Troy Ounce to Grams**: $1 \text{ troy oz} \equiv 31.1034768 \text{ grams}$ (Do NOT use avoirdupois $28.3495 \text{ g}$).
- **Global Benchmark to INR per Gram**:
  $$\text{Global Rate (INR/g)} = \frac{\text{XAU/USD} \times \text{USD/INR}}{31.1034768}$$
- **Fine Weight Calculation**:
  $$\text{Fine Weight (g)} = \text{Gross Weight (g)} \times \left(\frac{\text{Purity}}{1000}\right)$$
  - 24 Karat / 999.9 Fine: Purity factor = $0.9999$
  - 24 Karat / 995 Bullion: Purity factor = $0.995$
  - 22 Karat / 916 Jewelry: Purity factor = $0.916$
  - 18 Karat / 750 Jewelry: Purity factor = $0.750$
- **Domestic Spot Valuation**:
  $$\text{Current Valuation} = \text{Gross Weight (g)} \times \text{Spot Rate (INR/g)} \times \left(\frac{\text{Purity}}{999}\right)$$
- **Domestic Disparity / Premium**:
  $$\text{Domestic Premium (\%)} = \frac{\text{KJPL Rate} - \text{Global Rate (INR/g)}}{\text{Global Rate (INR/g)}} \times 100$$
  *Typical range: $+5.5\%$ to $+7.5\%$ reflecting India's Basic Customs Duty (6% BCD) and AIDC.*

---

## 3. Architecture & Code Conventions

### Backend (FastAPI + SQLAlchemy)
- Resilient persistence: Check connection strings; automatically fall back from PostgreSQL to SQLite (`data/goldsense.db`) in local developer environments without raising unhandled exceptions.
- Layered service architecture: Keep business logic inside `backend/app/services/` (`data_service.py`, `portfolio_service.py`, `alert_service.py`), keeping API route handlers lean.
- Schemas & Validation: Always use Pydantic models for request bodies and response schemas.
- Error handling: Return structured JSON with HTTP error codes (400 for bad input, 404 for missing items, 429 for rate limit/debounce).

### Frontend (Next.js 16 + Tailwind CSS)
- App router in `frontend/app/`.
- Single-page financial intelligence terminal layout with distinct visual tabs (Overview, Bullion Portfolio, AI Predictions, News Intelligence, Alerts).
- Clear freshness badges (`FRESH`, `DELAYED`, `STALE`) with timestamp annotations.
- Interactive modals for data entry (Add Holding modal) with client-side validation for positive weights and prices.

---

## 4. Testing Requirements

- Before committing any code, run the complete test suite:
  ```bash
  cd backend && pytest tests/ -v
  ```
- Any new service, route, or formula must have accompanying unit and integration tests.
- Invariants to assert in tests:
  - Correct conversion math for gold and silver.
  - User isolation (User A cannot access or delete User B's portfolio holdings).
  - Fine weight computation correctly handles both grams and kilograms.
  - Zero-lookahead alignment maintains target-feature invariant `len(dataset) == len(events) - 1`.
