# Error Handling, Resilience & Observability

## 1. Database Resilience Strategy
In a production deployment, GoldSense AI connects to PostgreSQL via `DATABASE_URL`. However, developers or offline environments may lack a running PostgreSQL daemon.

The connection manager in `backend/app/db/session.py` implements a graceful fallback pattern:
1. Tests the primary PostgreSQL connection with a strict 2-second socket timeout.
2. If connection fails or times out, logs a warning and automatically instantiates SQLite at `sqlite:///data/goldsense.db`.
3. Creates required tables automatically during application lifespan startup.

---

## 2. API Debounce & Rate Limiting
To prevent abuse of upstream collectors and avoid spamming external services:
- `/api/v1/market/refresh` enforces an in-memory 60-second cooldown per client IP/user.
- If invoked within the window, it immediately responds with `HTTP 429 Too Many Requests` containing the remaining seconds before the next allowed refresh.

---

## 3. Structured Logging & Health Checks
- The application uses Python's standard `logging` library configured to output timestamped, leveled logs (`INFO`, `WARNING`, `ERROR`).
- Endpoints return standard HTTP status codes:
  - `200 OK`: Successful retrieval or mutation.
  - `400 Bad Request`: Invalid input (e.g. negative weight or unrecognized purity).
  - `404 Not Found`: Holding or rule does not exist for the user.
  - `429 Too Many Requests`: Refresh cooldown triggered.
  - `500 Internal Server Error`: Unhandled application exception.
