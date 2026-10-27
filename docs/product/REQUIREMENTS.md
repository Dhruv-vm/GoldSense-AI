# Functional & Non-Functional Requirements

## 1. Functional Requirements (FR)

- **FR-1: Physical Rate Tracking**: The system must track KJPL Gold 999 (INR/g) and Silver 999 (INR/kg) rates from `data/kjpl/kjpl_rates.csv`.
- **FR-2: Global Benchmark Tracking**: The system must track COMEX Gold Futures (`GC=F`), Silver Futures (`SI=F`), and `USDINR=X` exchange rates from `data/market/market_rates.csv`.
- **FR-3: Metric Conversion**: Convert global USD troy ounce rates to INR per gram using $1 \text{ troy oz} = 31.1034768 \text{ grams}$.
- **FR-4: Domestic Premium Calculation**: Compute the percentage markup of Indian spot rate over global parity.
- **FR-5: Personal Bullion Portfolio**: Allow users to record physical gold and silver holdings with gross weight, purity (e.g. 999.9, 995, 916, 750), unit (g or kg), and acquisition cost.
- **FR-6: Valuation & Gain/Loss**: Compute fine metal weight, current market value, and unrealized gain/loss in INR and percentage.
- **FR-7: Multi-User Isolation**: Segment all portfolio records and custom alerts by `user_id`.
- **FR-8: News Sentiment Extraction**: Ingest financial RSS feeds, filter for bullion relevance, score using FinBERT, and extract sentiment score $[-1.0, 1.0]$.
- **FR-9: Machine Learning Prediction**: Train on daily macroeconomic features and sentiment signals with zero-lookahead bias.
- **FR-10: Transparent Low-Data State**: Alert users and flag prediction endpoints as `EXPERIMENTAL_DATA_COLLECTION` whenever training rows are fewer than 50.

---

## 2. Non-Functional Requirements (NFR)

- **NFR-1: Resilience & Fallbacks**: If PostgreSQL is unavailable, gracefully fall back to local SQLite without system crashing.
- **NFR-2: Performance**: Market overview and portfolio queries must respond in $< 100\text{ ms}$.
- **NFR-3: Refresh Rate Limiting**: Manual rate refresh requests must be debounced with a minimum 60-second cooldown per client.
- **NFR-4: Data Immutability**: Historical price CSVs are append-only; historical rate entries must never be mutated or fabricated.
