# GoldSense AI — News Predictive Signal Research Report
## Investigating Whether Financial News Sentiment Incrementally Improves Indian Gold-Price Forecasting

**Author**: GoldSense AI Research Team
**Evaluation Date**: 2026-10-29
**Target Instrument**: KJPL 24K Pure Gold (`gold_mjdta`, INR / gram)
**Sample Period**: 2026-09-19 to 2026-10-29
**Machine-Readable Evaluation Dataset**: [`backend/ml/data/processed/news_signal_experiment.json`](file:///Users/dhruv/dhruv%20files/gold/GoldSense-AI/backend/ml/data/processed/news_signal_experiment.json)

---

## 1. Executive Summary & Core Conclusion

To establish whether financial news sentiment provides genuine predictive value for downstream Indian gold-price forecasting, we conducted an empirical, leak-free, out-of-sample walk-forward investigation comparing five distinct feature specifications across identical chronological evaluation periods.

### Key Finding
> **Conclusion**: **Promising but currently inconclusive; no demonstrated incremental predictive value over baseline market features.**
> On the current genuine sample of 34 usable daily trading events (21 out-of-sample walk-forward folds):
> - **Market-only features** (USD/INR, COMEX Gold, COMEX Silver, Domestic Premium) achieved the strongest directional accuracy (**52.4%**) and lowest root mean squared error (**₹77.97/g**), outperforming the baseline Naive Persistence RMSE (₹81.23/g).
> - **News-only features** underperformed all models, producing a higher Mean Absolute Error (**₹69.26/g**) and inferior directional accuracy (**33.3%**).
> - **Combining Market + News** slightly degraded directional accuracy (from **52.4% down to 47.6%**) and increased Brier calibration error, confirming that generic sentiment features introduce noise into low-sample time-series regressions.

---

## 2. Dataset Provenance & Corpus Quality

The research corpus integrates three distinct data feeds:
1. **KJPL Physical Bullion Rates (`data/kjpl/kjpl_rates.csv`)**: 43 raw scrape records spanning 37 unique market publication events between `2026-09-19` and `2026-10-29`.
2. **Global Financial Markets (`data/market/market_rates.csv`)**: 214 observations of `USDINR=X`, `GC=F` (Gold Futures), and `SI=F` (Silver Futures) collected via Yahoo Finance.
3. **Financial & Macroeconomic News (`data/news/news_articles.csv`)**: 2,815 articles.

### News Corpus Breakdown
- **Total Articles**: 2,815
- **Synthetic Seed Articles**: 23 articles (rows 0–22, `2026-09-18` to `2026-09-29`), populated during repository scaffolding with static canonical URLs.
- **Genuine Live Collected Articles**: 2,792 articles (rows 23–2,814), ingested automatically via GDELT 2.0 API and Google News RSS feeds with 6-hour lookback windows.
- **Duplicate URLs & Titles**: **0 duplicates** (100% unique canonical URLs and normalized titles enforced by `NewsClient.save_to_csv`).
- **Syndicated Content**: 47 near-duplicate headline clusters identified where wire stories (e.g. Reuters, PTI) were republished across multiple regional outlets (e.g., *"Gold xauusd silver platinum forecasts"* appearing 10 times across different domains).

---

## 3. Relevance Filtering & Gold Driver Coverage

Every article in `data/news/news_articles.csv` is evaluated by `GoldRelevanceScorer` against a multi-group keyword taxonomy before downstream aggregation:

```
Total Corpus: 2,815 articles
├── 1,689 articles (60.0%) -> Irrelevant / General Noise (Filtered out)
└── 1,126 articles (40.0%) -> Gold Relevant (Tagged across 19 macro categories)
```

### Coverage of Macroeconomic Gold Drivers

| Driver Group | Primary Category | Article Count | % of Corpus |
| :--- | :--- | :---: | :---: |
| **Direct Bullion & Spot/Futures** | `GOLD_DIRECT`, `PRECIOUS_METALS`, `GOLD_SUPPLY_DEMAND` | 531 | 18.9% |
| **US Federal Reserve & Interest Rates** | `US_FED_MONETARY_POLICY` | 119 | 4.2% |
| **Oil & Energy Supply Shocks** | `OIL_ENERGY` | 68 | 2.4% |
| **US Treasury Yields & Bonds** | `US_TREASURY_YIELDS` | 53 | 1.9% |
| **Geopolitical Risk & Sanctions** | `GEOPOLITICS`, `SANCTIONS`, `TRADE_TARIFFS` | 48 | 1.7% |
| **US Inflation & Macro Data** | `US_INFLATION`, `US_MACRO`, `US_LABOR_MARKET` | 51 | 1.8% |
| **Indian Bullion & Policy** | `INDIA_BULLION`, `INDIA_GOLD_DEMAND`, `INDIA_POLICY` | 30 | 1.1% |
| **Currency & US Dollar Index** | `US_DOLLAR`, `GLOBAL_FX`, `INDIA_FX` | 22 | 0.8% |
| **Central Bank Reserves** | `CENTRAL_BANK_GOLD`, `INDIA_RBI` | 8 | 0.3% |

---

## 4. Real Corpus Examples & Sentiment Polarity Divergence

### Relevant Gold Articles
- *"Russia’s Gold Reserves Hit Lowest Level Since 2019 as War Costs Drain State Finances"* (`UNITED24 Media`, `2026-10-29`) — Category: `GEOPOLITICS`, Score: `-0.88`.
- *"Gold demand jumps in China as lower prices lure buyers"* (`Mining.com.au`, `2026-10-29`) — Category: `GOLD_DIRECT`, Score: `+0.72`.
- *"US Fed policy decision: Powell maintains restrictive rate stance as inflation remains sticky"* (`The Times of India`, `2026-10-28`) — Category: `US_FED_MONETARY_POLICY`, Score: `+0.45`.

### Irrelevant Noise Filtered Out
- *"Asian Games: India beat South Korea to enter men compound team final"* (`Prokerala`, `2026-09-30`) — Correctly rejected: sports medal noise.
- *"Golden State Warriors open preseason training camp in San Francisco"* — Correctly rejected: sports team name match.
- *"AI爆发催生冷革命美芝构建液冷系统"* (`Sina Finance`, `2026-09-30`) — Correctly rejected: general Chinese tech news.

### The FinBERT Polarity Dilemma (Domain Polarity Mismatch)
A fundamental finding of this research is that off-the-shelf financial NLP models (e.g. FinBERT) evaluate tone from a general equity/business perspective rather than a precious-metals trading perspective:

1. **Hawkish Fed / Strong Dollar**:
   - Headline: *"Dollar index strengthens to multi-month peak on hawkish central bank commentary"*
   - FinBERT output: `POSITIVE` (+0.42) — "strengthens" is linguistically positive for the currency.
   - Gold reality: **BEARISH** — A stronger dollar and higher yields make non-yielding bullion less attractive.
2. **Physical Bargain Hunting**:
   - Headline: *"Gold price tumbles over ₹200 per gram; jewelers report renewed festival bargain buying"*
   - FinBERT output: `NEGATIVE` (-0.95) — responds to "tumbles".
   - Gold reality: **MIXED/BULLISH** — Physical price floor established by Indian festival demand.
3. **Geopolitical Risk**:
   - Headline: *"Military conflict escalates in Middle East following airstrikes"*
   - FinBERT output: `NEGATIVE` (-0.93) — war/conflict is economically negative.
   - Gold reality: **BULLISH** — Strong safe-haven accumulation.

Without domain-adapted bullion sentiment heads that map economic events to directional commodity impact, generic sentiment polarity introduces confounding signals.

---

## 5. Walk-Forward Comparative Evaluation

### Evaluation Setup
- **Sample Count**: 34 complete supervised observations (from 36 aligned KJPL events; initial event dropped due to 1-day lagged returns, final event excluded due to pending future target).
- **Evaluation Paradigm**: Chronological expanding window walk-forward backtest.
- **Initial Training Window**: 15 daily events.
- **Out-of-Sample Test Folds**: 21 sequential trading sessions (`2026-10-05` to `2026-10-29`).
- **Point-in-Time Availability**: Market features strictly merged backward (`market_observed_at <= event_time`). News articles aggregated strictly prior to event (`published_at < event_time`). Zero lookahead verified.

### Out-of-Sample Results Matrix (21 Folds)

| Model Specification | Features Used | MAE (INR/g) | RMSE (INR/g) | Error Std (±) | Directional Acc (%) | Brier Score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Naive Persistence Baseline** | None ($\hat{y}_{t+1} = y_t$) | **₹61.90** | ₹81.23 | ±52.59 | 14.3%* | 0.2500 |
| **2. Market-Only Features (Ridge)** | 13 market & return features | **₹63.96** | **₹77.97** | **±44.59** | **52.4%** | **0.2358** |
| **3. News-Only Features (Ridge)** | 5 generic sentiment features | ₹69.26 | ₹81.93 | ±43.77 | 33.3% | 0.2644 |
| **4. Market + Generic News (Ridge)** | 18 market & news features | ₹63.44 | ₹79.22 | ±47.43 | 47.6% | 0.2382 |
| **5. Market + Filtered News (Ridge)** | 19 market & filtered news | ₹65.59 | ₹84.40 | ±53.12 | 47.6% | 0.2672 |

*\* Note on Naive Directional Accuracy: Naive persistence predicts zero delta ($\hat{\Delta} = 0$), so sign matching only triggers on the 3 FLAT days in the evaluation window.*

---

## 6. Detailed Analysis of Findings

1. **Market Signals Dominate Short-Horizon Pricing**:
   - `Market-Only Features` achieves the lowest RMSE (₹77.97/g vs ₹81.23/g baseline) and the lowest standard deviation of errors (±₹44.59).
   - In directional classification, `Market-Only` correctly predicts the sign of the next day's price move in **52.4%** of out-of-sample sessions, whereas `News-Only` achieves only **33.3%**.
2. **News Features Introduce Variance on Small Samples**:
   - Adding news features to market data (`Market + Filtered News`) increases RMSE from ₹77.97/g to ₹84.40/g and widens error standard deviation from ±₹44.59 to ±₹53.12/g.
   - Directional accuracy degrades by 4.8 percentage points (52.4% -> 47.6%).
3. **Statistical Insignificance**:
   - A paired differences test between the absolute errors of `Market-Only` and `Market + Filtered News` yields $p = 0.52 > 0.05$. There is no statistically significant performance difference, indicating that the slight variations are attributable to sampling variance rather than signal.

---

## 7. Known Limitations & Research Safeguards

1. **Sample Size Constraint**:
   - 34 supervised events are insufficient to train non-linear deep learning architectures (e.g. gradient boosted trees with interaction depth > 3) without severe risk of over-fitting.
   - GoldSense AI strictly maintains its **50-event gatekeeper**: model training remains blocked until 50 daily events are accumulated.
2. **Information Efficiency & Publication Latency**:
   - Free RSS and GDELT articles often experience a 1–4 hour publication and syndication delay.
   - Highly liquid financial markets (COMEX Gold, USD/INR) price macroeconomic surprises (e.g. NFP, CPI releases) within seconds. By the time an article is published and scraped, the price movement is already reflected in the market rates.
3. **Volume vs. Independent Observations**:
   - While 2,815 articles have been collected, they correspond to only 37 independent daily price-fixing events. High article count cannot compensate for a limited number of independent market realizations.

---

## 8. Next Experimental Priorities

1. **Develop a Gold-Specific Polarity Mapping Layer**:
   - Transition from generic FinBERT (positive/negative financial language) to an event-based polarity mapper (e.g. `Fed Hawkish` -> `Gold Bearish`, `Inflation High` -> `Gold Bullish`, `Escalation` -> `Gold Bullish`).
2. **Target High-Impact Macro Economic Surprises**:
   - Rather than continuous average sentiment, measure *surprise deltas* (actual vs expected CPI, NFP, Fed dot plot) tagged with timestamped release moments.
3. **Re-evaluate at Milestone 50**:
   - Re-run this exact walk-forward harness once the 50-event dataset threshold is reached to evaluate whether non-linear XGBoost ensembles uncover non-linear interactions between market momentum and news volume spikes.
