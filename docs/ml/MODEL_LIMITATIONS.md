# Model Limitations, Assumptions & Risk Disclaimers

## 1. Current Statistical Limitations
- **Sample Size Constraint**: With 36 aligned historical trading events (34 complete training rows), classical machine learning models (Random Forest, Gradient Boosting) are prone to high variance and overfitting if over-parameterized.
- **Enforced 50-Event Threshold**: Model training and live predictive inference remain strictly locked behind status `EXPERIMENTAL_DATA_COLLECTION` until at least 50 complete daily trading sessions have been observed.
- **Absence of Standalone News Predictive Value**: Out-of-sample walk-forward testing (see [News Signal Research Report](NEWS_PREDICTIVE_SIGNAL_RESEARCH.md)) demonstrates that generic financial sentiment scores currently fail to add incremental predictive value over baseline market metrics, and actually degrade directional accuracy (from 52.4% down to 47.6%) due to feature noise on small samples.
- **Decoupled Live News Intelligence vs. ML Regression**: Real-time news sentiment is deliberately decoupled from the quantitative price prediction engine. News serves as a qualitative intelligence and consensus layer on the dashboard rather than direct regression inputs.
- **Live News Freshness Limitations**: Live news intelligence requires at least 2 distinct unexpired semantic clusters within the active recency window (default 24h). If fresh volume drops below this threshold, the system reports `INSUFFICIENT_FRESH_RELEVANT_NEWS` rather than asserting low-confidence or misleading sentiment.

---

## 2. Key Market Assumptions
- **Customs Tariff Stability**: The model assumes Indian Basic Customs Duty (BCD) and AIDC remain constant. Major government budget announcements that alter import duties (e.g. Union Budget duty cuts) introduce structural breaks that historical models cannot anticipate.
- **Wholesale-to-Retail Spread**: Forecasts model wholesale bullion rates in Ahmedabad (KJPL). Retail jewelry prices involve additional hallmarking fees, wastage (3% to 15%), making charges, and 3% GST.

---

## 3. Financial Risk Disclaimer
GoldSense AI is an analytical research and personal bullion monitoring tool. **It does not constitute financial, investment, or trading advice.** Precious metals markets are subject to macroeconomic volatility, central bank policy shifts, and currency risks.
