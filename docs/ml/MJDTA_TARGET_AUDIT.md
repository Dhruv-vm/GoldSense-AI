# MJDTA Target Series Audit & Timestamp Remediation Report

- **Audited at (UTC):** `2026-11-11T12:56:39.230026+00:00`
- **Target Specification:** `MJDTA_GOLD_24K` | `EXCL_GST` | Purity `0.999` | Unit `INR_PER_1G`
- **Authoritative Live/Prospective Source:** PostgreSQL / Neon `bullion_rate_observations` (`MJDTA_GOLD_24K`, `validation_status='VALID'`).
- **Legacy Frozen CSV Preserved (`kjpl_rates.csv`):** 47 rows (45 eligible publications; 2 excluded Sunday/carry-over anomalies).
- **Legacy CSV Date Range:** `2026-09-19T14:36:43.157325+00:00` to `2026-11-10T07:42:29.003714+00:00`
- **Legacy Price Range (`INR/1g`):** `12775.0` – `14285.0`

## Legacy Archive Timestamp & Carry-Over Breakdown

| Timestamp Status | Count | Action |
|---|---:|---|
| `INFERRED_SAME_IST_DAY_CLOCK_ONLY` | 45 | Included (availability gated by `observed_at_utc`) |
| `STALE_REPEAT_CARRYOVER` | 1 | Excluded from target series (preserved in raw CSV) |
| `UNCERTAIN_SOURCE_DATE` | 1 | Excluded from target series (preserved in raw CSV) |

## Excluded / Uncertain Observations (Legacy CSV)

| Observed At (UTC) | Raw Published Time | Gold (INR/g) | Status | Reason |
|---|---|---:|---|---|
| `2026-09-20T10:00:56.408893+00:00` | `Time : 09:29 am` | 14285.00 | `STALE_REPEAT_CARRYOVER` | `exact_duplicate_published_time_and_gold_price_of_prior_observation` |
| `2026-11-01T11:21:53.598915+00:00` | `Time : 09:37 am` | 12730.00 | `UNCERTAIN_SOURCE_DATE` | `sunday_observation_with_clock_only_published_time_missing_source_date` |

## Continuity & Anti-Leakage Guarantees

1. Production and prospective forecasting read MJDTA observations directly from the configured database (`bullion_rate_observations`), failing closed if the database is unavailable (no silent fallback to stale CSV).
2. Legacy `kjpl_rates.csv` stores `Time : HH:MM am/pm` without an explicit source calendar date; weekend carry-overs and Sunday clock-only rows are quarantined without deleting raw history.
3. Point-in-time origin and horizon gating strictly enforce `available_at_utc = observed_at_utc`.
