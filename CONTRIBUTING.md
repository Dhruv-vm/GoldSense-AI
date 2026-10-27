# Contributing to GoldSense AI

Thank you for your interest in contributing to **GoldSense AI**. We follow strict engineering practices to maintain financial data integrity, avoid lookahead bias, and keep code modular and reliable.

---

## 1. Development Principles

1. **Branching Model**:
   - The primary active development branch is `develop`.
   - Never push directly to `main` without review.
   - Never use `git push --force`.
2. **Data Governance**:
   - Historical financial rates are strictly append-only.
   - Do not fabricate test records or modify feature timestamps to artificially enhance ML metrics.
3. **Scope Discipline**:
   - GoldSense AI is a personal bullion intelligence platform. Do not add commercial retail features such as POS, checkout, shopping carts, or invoicing.

---

## 2. Environment Setup

### Backend (FastAPI / Python)
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend (Next.js / Node.js)
```bash
cd frontend
npm install
```

---

## 3. Running Tests

Before submitting any Pull Request, ensure that the entire backend test suite passes:
```bash
cd backend
pytest tests/ -v
```

And verify the frontend builds cleanly without TypeScript or React warnings:
```bash
cd frontend
npm run build
```

---

## 4. Coding Standards

- **Python**:
  - Follow PEP 8 guidelines.
  - Use explicit type hints for all public functions and models.
  - Keep route handlers in `backend/app/api/routes/` thin, delegating business logic to `backend/app/services/`.
- **TypeScript / React**:
  - Use strict TypeScript typing.
  - Maintain accessible, responsive UI with Tailwind CSS.
  - Implement client-side input validation on all form inputs.
