# Model Limitations, Assumptions & Risk Disclaimers

## 1. Current Statistical Limitations
- **Sample Size Constraint**: With 34 aligned historical trading events, classical machine learning models (Random Forest, Gradient Boosting) are prone to high variance and overfitting if over-parameterized.
- **Intraday Collector Resolution**: Market rates are ingested at approximately 4.5-hour intervals via GitHub Actions runners, meaning high-frequency intraday momentum (15m, 1h) cannot be reliably resolved.

---

## 2. Key Market Assumptions
- **Customs Tariff Stability**: The model assumes Indian Basic Customs Duty (BCD) and AIDC remain constant. Major government budget announcements that alter import duties (e.g. Union Budget duty cuts) introduce structural breaks that historical models cannot anticipate.
- **Wholesale-to-Retail Spread**: Forecasts model wholesale bullion rates in Ahmedabad (KJPL). Retail jewelry prices involve additional hallmarking fees, wastage (3% to 15%), making charges, and 3% GST.

---

## 3. Financial Risk Disclaimer
GoldSense AI is an analytical research and personal bullion monitoring tool. **It does not constitute financial, investment, or trading advice.** Precious metals markets are subject to macroeconomic volatility, central bank policy shifts, and currency risks.
