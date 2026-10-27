# Dataset Schema & Feature Engineering

## 1. Feature Columns in `gold_training_dataset.csv`

Following the audit and pipeline repair, the production feature set consists of verified, non-null daily features:

| Feature Name | Category | Description |
| :--- | :--- | :--- |
| `gold_global_inr_per_gram` | Benchmark | Converted global spot in INR/g: $(\text{GC=F} \times \text{USDINR})/31.1034768$ |
| `silver_global_inr_per_kg` | Benchmark | Converted global silver spot in INR/kg |
| `xauusd_return_1d` | Momentum | 1-day percentage return of COMEX gold futures |
| `usdinr_return_1d` | Forex | 1-day percentage return of USD/INR |
| `silver_return_1d` | Momentum | 1-day percentage return of COMEX silver futures |
| `sentiment_score_mean` | Sentiment | Mean FinBERT sentiment score across 24h bullion news |
| `sentiment_score_std` | Sentiment | Standard deviation of FinBERT sentiment scores across 24h |
| `news_volume_24h` | Attention | Total number of bullion-relevant news articles in 24h |

---

## 2. Target Variable
- **Column**: `next_event_gold`
- **Definition**: The recorded KJPL Gold 999 rate (INR/g) at event index $t + 1$.
- **Invariant**: Because the last event in the historical sequence does not yet have a subsequent event, the training dataset row count satisfies:
  $$\text{len}(\text{training\_df}) = \text{len}(\text{unique\_kjpl\_events}) - 1$$
  *(Current: $35 - 1 = 34$ rows).*
