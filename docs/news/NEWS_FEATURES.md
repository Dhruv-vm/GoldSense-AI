# News Feature Engineering & Live Impact Signals

## 1. Feature Representation

### A. Point-in-Time Historical News Features (Zero-Lookahead ML Backtest)
For each physical market observation event at timestamp $T_{\text{event}}$, news articles published strictly within $[T_{\text{event}} - 24\text{h}, T_{\text{event}}[$ are aggregated:

1. **`sentiment_mean_1d`**:
   The mean sentiment score across all articles published in the 24-hour pre-event window:
   $$\bar{S} = \frac{1}{K} \sum_{k=1}^K S_k$$
   *(Defaults to $0.0$ if no articles were published).*

2. **`gold_sentiment_mean_1d`**:
   The mean sentiment score across exclusively gold-relevant articles in the pre-event window.

3. **`gold_relevant_ratio`**:
   The fraction of articles classified as gold-relevant: $\frac{K_{\text{gold}}}{K_{\text{total}}}$.

4. **`driver_specific_counts`**:
   Sub-counts measuring volume across specific macroeconomic catalysts: `fed_article_count`, `geopolitical_article_count`, `usd_article_count`, `central_bank_gold_article_count`.

---

### B. Freshness-First Bullion Impact Features (`fresh_news_walk_forward.py`)
To benchmark domain-specific bullion directional impact against generic sentiment, the pipeline evaluates:

1. **`fresh_bullish_weight`**:
   Time-decayed sum of bullish bullion catalyst weights:
   $$\sum_{i \in \text{Bullish}} e^{-\frac{\Delta t_i}{12}} \times \text{Conf}_i$$

2. **`fresh_bearish_weight`**:
   Time-decayed sum of bearish bullion catalyst weights (e.g., hawkish Fed rate hikes, surging dollar/yields).

3. **`fresh_net_gold_score`**:
   $$\text{Net Score} = \text{fresh\_bullish\_weight} - \text{fresh\_bearish\_weight}$$

4. **`fresh_cluster_count`**:
   Number of unique semantic headline clusters after deduplicating syndicated wire reprints.

---

## 2. Walk-Forward Empirical Benchmark Results

Walk-forward backtesting across 21 out-of-sample folds yields the following comparative performance:

| Feature Specification | MAE (₹/g) | RMSE (₹/g) | Directional Accuracy | Brier Score |
| :--- | :---: | :---: | :---: | :---: |
| **Naive Persistence Baseline** | ₹61.90 | ₹81.23 | 14.3% | 0.3643 |
| **Market-Only Features** | **₹62.62** | **₹74.29** | **61.9%** | **0.2452** |
| **Fresh News-Only (24h Bullion Impact)** | ₹76.88 | ₹89.50 | 38.1% | 0.3048 |
| **Market + Fresh News** | ₹67.76 | ₹81.68 | 47.6% | 0.2810 |

### Architectural Conclusion & Deployment Discipline
1. **Directional Improvement Over Generic Sentiment**:
   Commodity directional rules improve news-only directional accuracy from **33.3%** (generic FinBERT sentiment) to **38.1%** (bullion impact), confirming that aligning NLP with commodity economics reduces false polarity noise.
2. **Market Features Dominate Quantitative Regression**:
   Market-only features (COMEX Gold, USD/INR, Silver, Domestic Premium) provide superior predictive performance (61.9% directional accuracy, ₹74.29 RMSE).
3. **Decoupled Architecture**:
   Adding news features to the low-sample quantitative price regression degrades directional accuracy (from 61.9% to 47.6%) and increases variance. Therefore, GoldSense AI strictly decouples the live news signal: it is surfaced to users as an independent macroeconomic consensus and risk indicator (`GET /api/news/live-signal`), rather than being forced into the quantitative price forecasting regression.
