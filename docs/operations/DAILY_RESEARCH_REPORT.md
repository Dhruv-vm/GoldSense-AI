# VMD Bullion — Daily Operations & MJDTA Research Report

- **Generated at (UTC):** `2026-11-11T14:27:40.195220+00:00`
- **Protocol / Model:** `EXPERIMENT_PROTOCOL_V1` / `RIDGE_STD_V1`
- **Prospective Shadow Ledger Status:** `INSUFFICIENT_PROSPECTIVE_SAMPLES` (Origins logged: `0`, Matured: `0` / `30` required)
- **Backtest Study Status:** `INSUFFICIENT_SAMPLE`
- **Target Instrument:** `MJDTA_GOLD_24K` (`EXCL_GST`, Purity `0.999`, `INR/1g`) from DB `database`

## 1. MJDTA DB Series & Collector Health

- DB MJDTA total valid rows inspected: `1`
- Eligible distinct MJDTA publications: `1`
- Excluded weekend/uncertain rows: `0` (`{'VALID_EXPLICIT_TIMESTAMP': 1}`)
- Verified news coverage origins in backtest window: `0`
- Human review audit (`human_review_sample.csv`): `PENDING_HUMAN_ANNOTATIONS` (`0` / `250` labeled)

## 2. News Archive Provenance Summary

| Provenance Status | Count |
|---|---:|
| `SYNTHETIC_FIXTURE` | 23 |
| `HISTORICAL_UNVERIFIED_AVAILABILITY` | 3913 |
| `DUPLICATE` | 1 |

## 3. Latest Cutoff Snapshot & Frontier Arm Outputs

- **Origin Observed At (UTC):** `2026-11-11T09:26:04.307833+00:00`
- **Origin MJDTA 24K Gold (`INR/g`):** `13015.0`
- **News Cutoff Features:** `n_clusters_relevant=0`, `net_impact=UNAVAILABLE`, `unknown_share=UNAVAILABLE`, `coverage_ok=False`

| Mode | Horizon | Arm | Pred Log Return | Pred Price (INR/g) | Direction | P(Up) | Status |
|---|---:|---|---:|---:|---|---:|---|

## 4. Comparable-Origin Evaluation (`BACKTEST` Diagnostic Study)

### Horizon `h1` (Paired 4-Arm Comparable Origins: `0`)

| Arm | Bucket | Samples | Status | MAE (INR/g) | RMSE (INR/g) | Dir Acc | Brier |
|---|---|---:|---|---:|---:|---:|---:|
| `NO_CHANGE` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NO_CHANGE` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NO_CHANGE` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `PRICE_ONLY` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `PRICE_ONLY` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `PRICE_ONLY` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NEWS_ONLY` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NEWS_ONLY` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NEWS_ONLY` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `HYBRID` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `HYBRID` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `HYBRID` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |

- DM (`HYBRID vs PRICE_ONLY`, HLN Student-t): `{'status': 'INSUFFICIENT_SAMPLE', 'n': 0, 'min_required': 20, 'dm_stat': None, 'p_value_two_sided': None}`
- DM (`HYBRID vs NO_CHANGE`, HLN Student-t): `{'status': 'INSUFFICIENT_SAMPLE', 'n': 0, 'min_required': 20, 'dm_stat': None, 'p_value_two_sided': None}`

### Horizon `h3` (Paired 4-Arm Comparable Origins: `0`)

| Arm | Bucket | Samples | Status | MAE (INR/g) | RMSE (INR/g) | Dir Acc | Brier |
|---|---|---:|---|---:|---:|---:|---:|
| `NO_CHANGE` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NO_CHANGE` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NO_CHANGE` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `PRICE_ONLY` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `PRICE_ONLY` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `PRICE_ONLY` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NEWS_ONLY` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NEWS_ONLY` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `NEWS_ONLY` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `HYBRID` | `paired_comparable_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `HYBRID` | `all_valid_origins` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |
| `HYBRID` | `non_overlapping_paired` | 0 | `INSUFFICIENT_SAMPLE` | N/A | N/A | N/A | N/A |

- DM (`HYBRID vs PRICE_ONLY`, HLN Student-t): `{'status': 'INSUFFICIENT_SAMPLE', 'n': 0, 'min_required': 20, 'dm_stat': None, 'p_value_two_sided': None}`
- DM (`HYBRID vs NO_CHANGE`, HLN Student-t): `{'status': 'INSUFFICIENT_SAMPLE', 'n': 0, 'min_required': 20, 'dm_stat': None, 'p_value_two_sided': None}`

