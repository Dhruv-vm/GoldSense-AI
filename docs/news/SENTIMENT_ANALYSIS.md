# FinBERT Sentiment Analysis Engine

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

## 3. The Commodity Polarity Mismatch Dilemma
As detailed in the [News Signal Research Report](../ml/NEWS_PREDICTIVE_SIGNAL_RESEARCH.md), off-the-shelf financial NLP models evaluate tone from a general economic and corporate earnings perspective rather than a precious metals trading perspective:
- *"Dollar index strengthens to multi-month peak on hawkish central bank commentary"*
  - FinBERT: `POSITIVE` (+0.42) — "strengthens" is positive for the currency.
  - Bullion Reality: **BEARISH** — higher real yields and a stronger USD increase the opportunity cost of holding non-yielding gold.
- *"Military conflict escalates in Middle East"*
  - FinBERT: `NEGATIVE` (-0.93) — conflict is economically destructive.
  - Bullion Reality: **BULLISH** — flight to safety triggers rapid safe-haven accumulation.

Downstream modeling must therefore treat generic sentiment scores cautiously until an explicit commodity polarity mapping layer is trained.

---

## 4. Persistent Cache Synchronization
Because FinBERT inference requires substantial compute, results are cached in:
`backend/ml/data/processed/analyzed_news.csv`

The utility `backend/ml/training/sync_news_analysis.py` compares raw news in `data/news/news_articles.csv` against the cache and only scores newly ingested articles, achieving $O(N_{\text{new}})$ incremental cost. Total analyzed articles currently stands at 2,815.
