# FinBERT Sentiment Analysis Engine

## 1. Model Overview
GoldSense AI uses **FinBERT** (`ProsusAI/finbert`), a BERT language model pre-trained on the Financial PhraseBank and tailored specifically for financial text analysis.

General NLP sentiment models (such as VADER or standard BERT) misinterpret standard financial language. For example:
- *"Gold prices fell as bond yields surged"*
  - General model: Neutral or Positive (seeing "surged").
  - FinBERT: Correctly identifies **Negative / Bearish** for gold.

---

## 2. Sentiment Score Formulation
FinBERT returns probability logits for three classes:
$$P(\text{positive}), \quad P(\text{negative}), \quad P(\text{neutral})$$

The scalar sentiment score $S \in [-1.0, 1.0]$ is derived as:
$$S = P(\text{positive}) - P(\text{negative})$$

- $S > 0.15$: **Bullish / Positive** (green badge).
- $S < -0.15$: **Bearish / Negative** (red badge).
- $-0.15 \le S \le 0.15$: **Neutral** (slate badge).

---

## 3. Persistent Cache Synchronization
Because FinBERT inference requires substantial compute, results are cached in:
`backend/ml/data/processed/analyzed_news.csv`

The utility `backend/ml/training/sync_news_analysis.py` compares raw news in `data/news/news_articles.csv` against the cache and only scores newly ingested articles, achieving $O(N_{\text{new}})$ incremental cost.
