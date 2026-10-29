# FinBERT Sentiment Analysis & Bullion Impact Engine

## 1. Model Overview
GoldSense AI uses **FinBERT** (`ProsusAI/finbert`), a BERT language model pre-trained on the Financial PhraseBank and tailored specifically for financial text analysis.

General NLP sentiment models (such as VADER or standard BERT) misinterpret standard financial language. For example:
- *"Gold prices fell as bond yields surged"*
  - General model: Neutral or Positive (seeing "surged").
  - FinBERT: Correctly identifies **Negative** tone.

---

## 2. Sentiment Score Formulation
FinBERT returns probability logits for three classes:
$$P(\text{positive}), \quad P(\text{negative}), \quad P(\text{neutral})$$

The scalar sentiment score $S \in [-1.0, 1.0]$ is derived as:
$$S = P(\text{positive}) - P(\text{negative})$$

- $S > 0.15$: **Positive** (green badge).
- $S < -0.15$: **Negative** (red badge).
- $-0.15 \le S \le 0.15$: **Neutral** (slate badge).

---

## 3. Resolving the Commodity Polarity Dilemma: Bullion Impact Engine

Generic equity/financial NLP models evaluate tone from a general economic perspective rather than a precious-metals trading perspective:
- *"Dollar index strengthens to multi-month peak on hawkish central bank commentary"*
  - Generic FinBERT: `POSITIVE` (+0.42) — "strengthens" is positive for the currency.
  - Bullion Reality: **BEARISH** — higher real yields and a stronger USD increase the opportunity cost of holding non-yielding gold.
- *"Military conflict escalates in Middle East"*
  - Generic FinBERT: `NEGATIVE` (-0.93) — conflict is economically destructive.
  - Bullion Reality: **BULLISH** — flight to safety triggers rapid safe-haven accumulation.

To resolve this conflict, GoldSense AI implements an explicit **Domain-Specific Bullion Direction Mapping Layer** (`backend/app/services/sentiment/gold_impact.py`):

| Macro Transmission Channel | Headline Catalyst Pattern | Commodity Implication | Economic Rationale |
| :--- | :--- | :---: | :--- |
| **US Fed & Interest Rates** | Hawkish hikes, rising bond yields | **BEARISH** | Rising yields increase the opportunity cost of holding non-yielding bullion. |
| **US Fed & Interest Rates** | Dovish pause, rate cuts expected | **BULLISH** | Diminishing real yield hurdles support capital allocation into physical gold. |
| **US Dollar FX** | Dollar strengthens, DXY rallies | **BEARISH** | A stronger greenback increases bullion acquisition costs for foreign buyers. |
| **US Dollar FX** | Dollar weakens, Rupee depreciates | **BULLISH** | Currency weakness increases domestic landing costs and boosts INR spot rates. |
| **Geopolitics & Safe-Haven** | War, escalation, airstrikes, sanctions | **BULLISH** | Geopolitical crisis accelerates safe-haven reserve and sovereign ETF buying. |
| **Physical & Central Bank** | Central bank gold reserves, festival buying | **BULLISH** | Sovereign and retail accumulation establishes a structural physical price floor. |
| **Market Momentum** | Bullion rallies to record, technical breakout | **BULLISH** | Technical momentum attracts systematic and futures trend-following capital. |
| **Market Momentum** | Sell-off in gold, prices retreat | **BEARISH** | Profit-taking and liquidation indicate active intraday downward pressure. |

---

## 4. Freshness-First Time-Decay & Syndicated Clustering

Live news signals prioritize fresh, market-moving events over stale coverage using:
1. **Exponential Recency Weighting**:
   $$w_i = e^{-\frac{\Delta t}{12}}$$
   where $\Delta t$ is the age in hours from observation time. A story breaking 1 hour ago receives a weight of $\approx 0.92$, whereas a story from 24 hours ago decays to $\approx 0.14$.
2. **Syndicated Wire Headline Clustering**:
   Wire stories republished under identical or near-identical headlines across syndicated networks (Reuters, PTI, regional publishers) are normalized by semantic token stems (`extract_cluster_key`) and clustered together. Only the highest-confidence representative article is weighted, preventing repetitive wire reports from artificially multiplying signal power.
3. **Safety Guard for Low Fresh Corpus**:
   If fewer than 2 distinct clusters exist within the active recency window, the service honestly returns `status: INSUFFICIENT_FRESH_RELEVANT_NEWS` rather than inventing false sentiment or guessing.

---

## 5. Persistent Cache Synchronization
FinBERT inference results are cached in:
`backend/ml/data/processed/analyzed_news.csv`

The utility `backend/ml/training/sync_news_analysis.py` compares raw news in `data/news/news_articles.csv` against the cache and only scores newly ingested articles, achieving $O(N_{\text{new}})$ incremental cost. Total analyzed articles currently stands at 2,815+.
