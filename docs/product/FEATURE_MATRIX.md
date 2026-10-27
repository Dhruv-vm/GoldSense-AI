# Feature Matrix & Functional Scope

| Feature Area | Component | Implementation Status | Notes & Capabilities |
| :--- | :--- | :--- | :--- |
| **Market Rates** | KJPL Rate Ingestion | **Production Ready** | Scrapes Ahmedabad 24K Gold & 999 Silver spot rates. |
| | Global Benchmark Ingestion | **Production Ready** | Pulls `GC=F`, `SI=F`, and `USDINR=X` via Yahoo Finance. |
| | Global to INR/g Conversion | **Production Ready** | Mathematical conversion using standard Troy ounce factor ($31.1034768$). |
| | Domestic Premium Metric | **Production Ready** | Calculates difference between local Indian rate and global landed rate (typically $+5.5\%$ to $+7.5\%$). |
| | Debounced Rate Refresh | **Production Ready** | On-demand UI refresh with 60-second cooldown protection. |
| **Portfolio Tracker** | Multi-Metal Asset Support | **Production Ready** | Gold and Silver support across varying purities (999.9, 995, 916, 750). |
| | Gram & Kilogram Inputs | **Production Ready** | Automatic conversion to gross grams and fine metal content. |
| | Mark-to-Market Valuation | **Production Ready** | Real-time valuation based on latest spot rates and unrealized PnL. |
| | Multi-User Data Isolation | **Production Ready** | Data segmented by `user_id` with `X-User-ID` header routing. |
| | Commercial Invoicing / POS | **Excluded by Design** | Strict personal wealth scope; commercial sales workflows omitted. |
| **News Intelligence** | RSS Ingestion Pipeline | **Production Ready** | Automated collection across global and Indian financial news desks. |
| | Gold Relevance Filtering | **Production Ready** | Lexical and thematic filtering for precious metals topics. |
| | FinBERT Sentiment Analysis| **Production Ready** | Financial NLP scoring (positive, negative, neutral, confidence score). |
| | Cache Synchronization | **Production Ready** | Incremental synchronization tool `sync_news_analysis.py`. |
| **ML Predictions** | Zero-Lookahead Merge | **Production Ready** | Feature generation adhering strictly to point-in-time publication cutoffs. |
| | Model Training Script | **Production Ready** | Random Forest / Gradient Boosting trained on daily macro returns & sentiment. |
| | Honest Data State Check | **Production Ready** | Emits `EXPERIMENTAL_DATA_COLLECTION` state when samples $< 50$. |
| **Alerts & Triggers** | Threshold Rule Engine | **Production Ready** | Monitors spot rate crosses and domestic premium percentage breaches. |
