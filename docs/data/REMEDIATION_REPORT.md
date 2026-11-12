# VMD BULLION — HISTORICAL DATA REMEDIATION REPORT (PHASE 2)

> **Executed At:** 2026-11-11T08:42:25.579491+00:00  
> **Script:** `scripts/remediate_historical_data.py`

## Summary

All corrupted, mis-parsed, duplicate, and test-fixture-contaminated records have been preserved in immutable quarantine CSVs and excluded from active rate tables, charts, and calculations.

### 1. `data/kjpl/city_rates.csv`
- **Original Rows:** 133
- **Valid Genuine Observations Retained:** 8
- **Quarantined / Invalidated Rows Moved to `data/kjpl/quarantined_city_rates.csv`:** 125
- **Breakdown by Reason:** {'FIXTURE_CONTAMINATION': 110, 'PRICE_OR_UNIT_CONTAMINATION': 15}

#### Notable Historical Defects Remediated:
- **110 Test Fixture Rows:** Synthetic `kjpl_live_sample.html` rows (`Time : 09:35 am`, `13085000.0`, `1308500.0`, including 9× Oct 31 duplicates and 1× Nov 10 copy) accidentally appended by unisolated `test_kjpl_city_extraction.py`.
- **15 Parser Contamination Rows:**
  - `200.0` / `205.0` / `210.0` (silver rates saved under `ALL_INDIA / MJDTA_GOLD_24K` from combined table header).
  - `4043.65` (LBMA Gold AM USD/oz saved under `MJDTA_GOLD_24K`).
  - `50.1`, `51.99`, `52.82`, `52.02`, `52.625`, `52.285` (LBMA Silver USD/oz saved under `MJDTA_SILVER`).
  - `100.0` (`com_display_purity` / product weight parsed as gold rate for Chennai, Bengaluru, Mumbai) and `51.0` / `52.0` (`com_id` parsed as gold rate for Coimbatore and Hyderabad).

### 2. `data/kjpl/kjpl_rates.csv`
- **Original Rows:** 53
- **Valid Unique Observations Retained:** 47
- **Quarantined Duplicates Moved to `data/kjpl/quarantined_kjpl_rates.csv`:** 6
- **Breakdown by Reason:** {'DUPLICATE_EVENT': 6}

### 3. Local SQLite Database (`data/goldsense.db`)
- Rebuilt via strict Alembic migration chain (`a7c3e91b42d0`) with `Numeric(14, 2)` precision.
- Replayed **8** valid verified historical observations cleanly.
