# VMD Bullion MJDTA Forecasting — Pre-Registered Experiment Protocol (`EXPERIMENT_PROTOCOL_V1`)

- **Protocol Version:** `EXPERIMENT_PROTOCOL_V1`
- **Model Version:** `RIDGE_STD_V1`
- **Target Series:** `MJDTA_GOLD_24K` (`city_code='CHENNAI'`, `source_product_id='MJDTA_GOLD'`, `EXCL_GST`, `purity=0.999`, observation `unit='1g'` and `rate_type='MJDTA_BENCHMARK'`) read exclusively from PostgreSQL / Neon `bullion_rate_observations` (`validation_status='VALID'`), preserving every distinct `source_published_at` publication (changed or unchanged). When the source re-publishes a corrected price under the same `source_published_at`, an immutable linked `CORRECTION` row (`supersedes_observation_id`, incremented `revision_number`) is appended, original forecasts and evaluations remain unchanged, any correction-aware reassessment is stored separately in `forecast_evaluation_reassessments`, and no duplicate eight-arm prospective forecast set is generated for the same publication. MJDTA rows whose source timestamp is missing, future (`source_published_at > observed_at`), or an ambiguous clock-only time ahead of collection without established carryover evidence are quarantined with raw clock metadata preserved.
- **Protocol Freezing:** this file is frozen by SHA-256. `app/services/prediction/protocol.py` holds `EXPERIMENT_PROTOCOL_V1_SHA256`, which is enforced BOTH by `tests/test_protocol_freeze.py` AND at runtime before every `PROSPECTIVE` forecast generation/persistence call (`verify_runtime_protocol()`), persisting the verified hash on `forecast_runs` and `research_feature_snapshots` (pre-existing legacy rows retain `NULL`). Any edit to this file is a protocol amendment and must be recorded in Section 6.
- **DB enforcement (what the triggers and roles actually cover):** migrations `e8b3c1d45207`, `f3c7a2d9e1b4`, and `9b4e1d8c3a02` install PostgreSQL triggers (with SQLite row-level equivalents) that: (a) block UPDATE/DELETE of `PROSPECTIVE` rows in `forecast_runs`, `research_feature_snapshots`, and `forecast_evaluations`, plus promotion of `BACKTEST` rows; (b) validate `PROSPECTIVE` `forecast_evaluations` BEFORE INSERT against `forecast_runs` and the authoritative MJDTA series (`target_observation_id`, horizon publication rank, `matured_observed_at`, `actual_price_inr_per_g`, `actual_log_return`, `actual_direction`); (c) validate `news_labels` BEFORE INSERT against `news_clusters`, `news_articles`, and `news_collection_runs`, pinning DB-controlled `db_recorded_at` and `available_at` (`NOW()` when unlinked to an active open run); (d) make `news_labels`, `news_collection_runs`, `bullion_rate_observations`, and `forecast_evaluation_reassessments` append-only; (e) enforce concurrent idempotency for non-deterministic/LLM labels via `uq_news_label_llm_identity`; and (f) block `TRUNCATE` on all protected ledger tables. Role separation (`deploy/neon/roles_and_grants.sql`) keeps table/trigger ownership on `vmd_migrator` (`NEON_MIGRATION_DATABASE_URL`) while restricting runtime workers/APIs (`vmd_app_runtime`, `NEON_RUNTIME_DATABASE_URL`) to `SELECT`/`INSERT` on ledgers with zero DDL/trigger/truncate rights.
- **Application enforcement:** the remaining rules (cutoff gating, arm availability, DM gating) are enforced in `forecast_engine.py` and `news_features.py` and covered by the test suite, not by the database.
- **Primary Horizon (`h=1`):** Next valid distinct MJDTA publication (`log_return = ln(P_{t+1} / P_t)` and implied `INR/g = P_t * exp(pred_log_return)`)
- **Secondary Horizon (`h=3`):** Three valid distinct MJDTA publications ahead (`log_return = ln(P_{t+3} / P_t)`), evaluated both on HAC-adjusted valid pairs and non-overlapping origins (without double HAC+HLN adjustment on non-overlapping stride=3 splits)

## 1. Strict Separation of Prospective Ledger vs Historical Backtest (`F-02`)

1. **`PROSPECTIVE` Mode (`generation_mode='PROSPECTIVE'`):**
   - Generated strictly **before** any `t + h` target observation exists in `bullion_rate_observations` (`target_observation_id IS NULL`, `target_observed_at IS NULL` at creation, `generated_at >= origin_observed_at`).
   - Any attempt to write retrospective / hindsight origins into the `PROSPECTIVE` ledger raises a hard validation error.
2. **`BACKTEST` Mode (`generation_mode='BACKTEST'`):**
   - Strictly descriptive chronological expanding-window diagnostic replay; never mixed into prospective maturity counts or claims.

## 2. Anti-Leakage & Label Immutability Rules (`F-03`, `F-07`, `F-10`)

1. **System Isolation:** Live 5-city retail bullion rates (`city_id` `48..52`), `ALL_INDIA` ID `47` / `'GOLD'`, and GST-included `MJDTA_GOLD_24K_GST` NEVER enter MJDTA targets or features.
2. **External Spot Ban:** Zero Yahoo Finance (`yfinance`), XAUUSD/LBMA, USDINR, or MCX predictors are allowed.
3. **Append-Only News Labels:** Feature extraction strictly reads persisted `news_labels` rows satisfying BOTH `first_seen_at <= T` AND `label_created_at <= T`, aggregated deterministically per cluster and tagged with implementation `model_digest` (a SHA-256 over the evaluator source and the full `gold_impact` / `provenance` module sources, so rule-table edits change it). The deterministic-rules label never mixes in LLM (Ollama) outputs; each model keeps its own label lineage. Legacy offline `walk_forward_evaluation.py` FinBERT outputs remain strictly isolated from `EXPERIMENT_PROTOCOL_V1`.
4. **Coverage & Quiet-Day vs Missing-News Semantics (`F-10`):** Collector health is judged by the **latest** run completed inside the lookback window. When that run failed, was degraded (<50% queries succeeded), or no run is recorded (`collector_healthy == False`), `coverage_ok = False`, `net_impact` / `unknown_share` remain `NULL`, and `NEWS_ONLY` / `HYBRID` emit `UNAVAILABLE_NO_NEWS_COVERAGE`. When collector runs succeed on quiet days with 0–1 macro clusters, observed coverage remains `coverage_ok = True` (`net_impact = 0.0` if 0 clusters) to eliminate news-heavy selection bias.

## 3. Paired Standardized Arms (`F-08`, `F-18`)

- Zero undeclared heuristic priors: if matured training pairs `< 10` (`MIN_TRAINING_ORIGINS`) or `coverage_ok == False`, the affected statistical arm returns `UNAVAILABLE` / `INSUFFICIENT_SAMPLE` (`NULL`) rather than fallback heuristics.
- Every active statistical arm standardizes features strictly using `(mu_train, sigma_train)` from within its expanding training window (`available_at(j+h) <= T`) prior to Ridge (`alpha = 5.0`) solve.
- `up_probability` outputs represent **raw uncalibrated model scores** derived from training residual scale (`sigma_err`), NOT empirically calibrated probabilities.

## 4. Comparable-Origin Evaluation & HLN Student-t DM Test (`F-09`, `F-14`)

- Comparative evaluation across arms runs strictly on **common valid paired origins** (`paired_comparable_origins`) where all 4 arms produced valid predictions.
- Diebold-Mariano statistics apply Newey-West/Bartlett HAC (`max_lag = h - 1`), the **Harvey-Leybourne-Newbold (1997)** finite-sample correction, and two-sided **Student's t (`df = n - 1`)** p-values, explicitly gating `n < 20`, unpaired inputs, identical predictions, and degenerate non-positive HAC variance.
- Overall statistical readiness requires `MIN_EVALUATION_SAMPLES = 30` matured prospective comparable pairs; below this threshold all metrics remain descriptive under `INSUFFICIENT_PROSPECTIVE_SAMPLES`.

## 5. Label Versions

- `SENTIMENT_VERSION = GOLD_SENTIMENT_V3`, `CLUSTER_VERSION = CLUSTER_V3` (Audit #3 fixes: AS_EXPECTED Fed actions → NEUTRAL; negated-cut phrasing → BEARISH; foreign CB policy → UNKNOWN / OTHER_MACRO; macro events inside "gold price today" bulletins are no longer swallowed as price reports; story clusters do not merge headlines that differ in a number, a data release / central bank / asset, or reported direction).

## 6. Amendment Log

| Date | Change |
|---|---|
| 2026-11-11 | Audit #3 remediation: DB-enforcement scope stated accurately; SHA-256 freeze added; target filters and same-publication correction rule; latest-run coverage rule; label version bump to V3. |
| 2026-11-12 | Audit #3 Final remediation (`9b4e1d8c3a02`): runtime protocol SHA-256 enforcement; DB BEFORE INSERT validation for `forecast_evaluations` and `news_labels` (`available_at`); PostgreSQL runtime-role isolation; linked MJDTA correction lineage & separate `forecast_evaluation_reassessments`; non-future `source_published_at` & ambiguous clock-only quarantine; concurrent Ollama unique identity constraint; AST comment/docstring-free classifier digest. |
