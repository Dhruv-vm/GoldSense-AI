# Rate Refresh Lifecycle, Freshness & SSE Streaming

## 1. Freshness Classification
To provide transparent visibility into market quote latency, VMD Bullion labels rates using truthful operational tiers:

| Badge | Condition / Threshold | Significance |
| :--- | :--- | :--- |
| **`LIVE`** | Continuous Pipeline B WS / `kjpl.txt` sync active | Real-time KJPL live terminal observation. |
| **`FRESH`** | $< 10\text{ minutes}$ | High-confidence verified KJPL quote. |
| **`DELAYED`** | $10\text{ to } 60\text{ minutes}$ | Standard intraday batch interval. |
| **`STALE`** | $> 60\text{ minutes}$ | Upstream quote has exceeded active freshness threshold. |
| **`MARKET_CLOSED`** | KJPL `Type 4` status flag = closed or outside active session | Official market closed state (unchanged last closing rate). |
| **`SOURCE_UNAVAILABLE`** | Upstream fetch unreachable or field missing | Genuine unavailability; never replaced with fabricated values. |
| **`QUARANTINED`** | Failed `validator.py` purity/unit sanity check | Isolated for audit; excluded from live KPIs. |

---

## 2. SSE Real-Time Delivery & Manual Sync
- **Automatic Live Updates**: Frontend subscribes via `EventSource` to `GET /api/bullion/stream`, emitting `snapshot` frames only when PostgreSQL `BullionLatestRate` advances.
- **Manual Terminal Refresh**: Reloads verified persisted state via `GET /api/bullion/dashboard` (`POST /api/v1/market/refresh` no longer calls Yahoo Finance; spot parity uses persisted KJPL `SPOT-GOLD`, `SPOT-SILVER`, and `SPOT-INR`).
