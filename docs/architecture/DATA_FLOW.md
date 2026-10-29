# Data Flow & Point-in-Time Cutoff Rules

## 1. End-to-End Data Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Client
    participant Frontend as Next.js Dashboard
    participant API as FastAPI Backend
    participant DataSvc as DataService / DB
    participant ML as ML Prediction Engine
    participant Sources as External Sources (KJPL, YF, RSS)

    Sources->>DataSvc: Ingest rates & news into CSVs (Cron/Workflow)
    User->>Frontend: Open Financial Terminal
    Frontend->>API: GET /api/v1/market/overview
    API->>DataSvc: Get latest rates & compute domestic premium
    DataSvc-->>Frontend: Return Gold/Silver spot, global parity, premium %

    User->>Frontend: View Portfolio
    Frontend->>API: GET /api/v1/portfolio (with X-User-ID)
    API->>DataSvc: Calculate holdings valuation using latest spot
    DataSvc-->>Frontend: Return fine weights, total value, unrealized PnL

    User->>Frontend: View AI Prediction
    Frontend->>API: GET /api/v1/prediction/latest
    API->>ML: Evaluate model readiness & features
    ML-->>Frontend: Return EXPERIMENTAL_DATA_COLLECTION (34 samples)
```

---

## 2. Zero-Lookahead Bias & Point-in-Time Discipline

Machine learning in financial markets requires strict point-in-time boundaries to eliminate lookahead bias:

1. **Event Cutoff ($T_{event}$)**:
   - For every KJPL observation at date $T_{event}$, the target is set to the price of the *subsequent* event:
     $$y_{t} = \text{Price}(T_{t+1})$$
   - All feature columns $X_{t}$ must only use market data and news published **on or before** $T_{event}$:
     $$X_{t} \in \mathcal{F}(t \le T_{event})$$

2. **Market Return Windowing**:
   - `xauusd_return_1d`, `usdinr_return_1d`, and `silver_return_1d` are computed based on the previous close relative to $T_{event}$.
   - Intraday high-frequency returns (15-min and 1-hour) are excluded unless continuous high-frequency order books are ingested.

3. **News Sentiment Aggregation**:
   - For event $T_{event}$, only news articles satisfying:
     $$T_{event} - 24\text{ hours} \le t_{\text{published}} \le T_{event}$$
     are included in the sentiment aggregation (`sentiment_score_mean`, `sentiment_score_std`, `news_volume_24h`).
   - Articles published after $T_{event}$ are never used in constructing $X_{t}$.
