# Testing & Test Suite Guide

## 1. Running the Test Suite
The backend uses `pytest` for unit and integration testing.

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

---

## 2. Test Coverage & Structure

- **`backend/tests/test_portfolio_service.py`**:
  - Tests gross-to-fine weight calculations across 999.9, 995, 916, and 750 purities.
  - Tests unit conversions (grams and kilograms).
  - Tests multi-user isolation (asserts user A cannot access or delete user B's holdings).
  - Tests valuation and unrealized gain/loss arithmetic.
- **`backend/tests/test_api_endpoints.py`**:
  - Tests `/api/v1/market/overview` and domestic premium logic.
  - Tests `/api/v1/market/refresh` debounce rate limiter (asserts HTTP 429 upon rapid subsequent call).
  - Tests `/api/v1/prediction/latest` response payload and experimental warning.
  - Tests `/api/v1/news` and `/api/v1/alerts`.
- **`backend/tests/test_dataset_alignment.py`**:
  - Asserts zero-lookahead feature alignment invariants.
  - Verifies $\text{len}(df) = \text{len}(\text{events}) - 1$.
- **`backend/tests/test_finbert.py`**:
  - Validates financial sentiment scoring and classification thresholds.

---

## 3. Frontend Build Validation
Ensure the frontend builds without TypeScript compilation errors:
```bash
cd frontend
npm run build
```
