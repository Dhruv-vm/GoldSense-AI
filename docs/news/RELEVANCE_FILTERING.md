# Article Relevance Filtering

## 1. Domain Inclusion Rules
To prevent general macroeconomic noise (e.g. tech stock earnings) from polluting bullion sentiment features, articles undergo a strict relevance check.

An article is classified as `is_gold_relevant = True` if its title or summary contains:
- **Direct Gold Keywords**: `gold`, `xauusd`, `yellow metal`, `bullion`, `sovereign gold bond`, `sgb`.
- **Precious Metals Keywords**: `precious metals`, `silver`, `xagusd`, `platinum`, `palladium`.
- **Monetary & Reserve Keywords**: `central bank gold`, `rbi gold reserves`, `fed interest rates`, `dollar index`, `dxy`, `rate cut`, `treasury yields`.

---

## 2. Exclusion & De-biasing Rules
Articles that mention "gold" only in figurative or non-financial contexts (e.g. "Olympic gold medal", "Golden Globe award", "golden retriever") are excluded via negative lexical filtering.
