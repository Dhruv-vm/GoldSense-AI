# Article Relevance Filtering & Driver Taxonomy

## 1. Domain Inclusion Rules
To prevent general macroeconomic noise (e.g. tech stock earnings) from polluting bullion sentiment features, articles undergo a strict relevance check.

An article is classified as `is_gold_relevant = True` if its title or summary matches our macroeconomic bullion taxonomy:
- **Direct Gold Keywords**: `gold`, `xauusd`, `yellow metal`, `bullion`, `sovereign gold bond`, `sgb`.
- **Precious Metals Keywords**: `precious metals`, `silver`, `xagusd`, `platinum`, `palladium`.
- **Monetary & Reserve Keywords**: `central bank gold`, `rbi gold reserves`, `fed interest rates`, `dollar index`, `dxy`, `rate cut`, `treasury yields`.

---

## 2. Exclusion & De-biasing Rules
Articles that mention "gold" only in figurative or non-financial contexts are excluded via negative lexical filtering:
- Olympic & sports medals: `"olympic gold"`, `"compound team"`, `"medal tally"`.
- Entertainment awards: `"golden globe"`, `"grammy"`.
- Sports franchises: `"golden state warriors"`.
- Non-financial animal/nature idioms: `"golden retriever"`, `"golden eagle"`.

---

## 3. Macroeconomic Transmission Channel Taxonomy (`GoldDriver`)

Articles classified as relevant are attributed to specific transmission channels in `backend/app/services/sentiment/gold_impact.py`:
1. `US_FED_RATES`: Federal Reserve rate policy, FOMC statements, Treasury yield trajectories.
2. `US_DOLLAR_FX`: US Dollar Index (DXY), foreign exchange fluctuations, USD/INR depreciation.
3. `INFLATION_MACRO`: CPI releases, core PCE deflator, macroeconomic growth indicators.
4. `GEOPOLITICS_SAFE_HAVEN`: Escalations, military conflict, sanctions, flights to safety.
5. `PHYSICAL_AND_CENTRAL_BANK`: Sovereign reserve accumulation (RBI, PBOC), physical retail & festival buying.
6. `MARKET_MOMENTUM`: Technical breakout, record highs, liquidation sell-offs.
7. `OTHER_MACRO`: Broad commentary without direct identifiable transmission channel.

---

## 4. Syndicated Wire Stem Clustering
To prevent news aggregators and syndicated wire reprints (e.g., Reuters wire stories picked up across 10 regional domains) from inflating article counts, `extract_cluster_key` extracts semantic token stems after stripping publisher attribution and stop words:
- Wire Reprint 1: `"Fed Holds Interest Rates Steady Amid Inflation Worries - Reuters"`
- Wire Reprint 2: `"Fed Holds Interest Rates Steady Amid Inflation Worries - Bloomberg"`
- Wire Reprint 3: `"Fed Holds Interest Rates Steady Amid Inflation Worries | Financial Times"`
- **Cluster Key**: `"fed holds interest rates steady"`

The live signal groups these 3 stories into a single cluster with 3 syndicated copies, weighting only the highest-confidence representative article.
