# VMD Bullion — Independent Forensic Technical Audit

**Date:** 2026-11-11 · **Auditor:** Claude (independent; did not author the implementation)
**Subject:** Antigravity's uncommitted research/engineering upgrade in the local working tree `~/dhruv files/gold/GoldSense-AI`
**Method:** Read-only. A copy of the working tree was audited in an isolated container. Nothing in the repo was modified, committed, reset or pushed. Every count was reproduced, tests were run, adversarial tests were run against the production code paths, and Alembic was exercised against a real local **PostgreSQL 16.15**. **Live Neon was NOT tested.**

---

## A. Executive verdict

# FAIL — CRITICAL DEFECTS FOUND

Much of the engineering is solid:
- The five-city mapping and city isolation are correct.
- The MJDTA target is correctly isolated from city and external prices.
- Archive counts reproduce exactly and deterministically.
- The future-price, first-seen-after-T and unverified-article leakage gates hold.
- Migrations upgrade, downgrade and pass `alembic check` on real PostgreSQL.
- The DM arithmetic matches an independent implementation.

But three defects make the system **not ready for prospective shadow forecasting**, and several more make the reported results misleading:

1. **The MJDTA target series stops growing once the new workflows are deployed.** CI writes MJDTA only to Neon, but the forecast engine reads only `data/kjpl/kjpl_rates.csv`, which CI no longer updates.
2. **The "immutable shadow forecast" ledger is seeded with hindsight.** The first persistence run inserts 304/304 forecasts *after* their targets were already known, with nothing marking them as backfilled (verified on PostgreSQL).
3. **News labels are recomputed on every load and back-dated** (`label_created_at := first_seen_at`). The `label_created_at <= T` gate therefore does nothing, and any rule change silently rewrites historical features (demonstrated: net_impact +0.0851 → −0.0851).

The news and model arms are also currently degenerate:
- PRICE_ONLY collapses to a constant drift.
- NEWS_ONLY equals 0.0 at 38/40 origins, yet is reported as `EVALUATED`.
- HYBRID equals PRICE_ONLY at 38/40 origins.

The Fed rules assign the **wrong sign** to common dovish headlines.

---

## B. Repository integrity

| Item | Observed |
|---|---|
| Branch | `develop` |
| HEAD | `06fdf0a` (2026-11-10 21:17 IST) |
| Working tree | **62 modified, 43 untracked, 0 deleted, nothing staged** |
| Remote | `origin/develop` is **9 bot commits ahead** (`8c98109`, 2026-11-11 10:29 UTC). The GitHub Actions workflows still running there are the *old* auto-committing versions. |
| Secrets | No `.env` tracked or staged; `.env.example` contains placeholders only; no credential-shaped URLs found. |
| Local DB | `data/goldsense.db` exists but is gitignored (not tracked). |
| yfinance | No runtime import. It appears only in comments and a decommissioned stub (`scripts/collect_market_csv.py`, `market-collector.yml` is dispatch-only). |
| Supabase | No runtime dependency; only `scripts/verify_supabase_connection.py` remains (dead script). |
| Quarantine preservation | 6 rows removed from `kjpl_rates.csv` are byte-identical in `quarantined_kjpl_rates.csv`. 125 rows were removed from `city_rates.csv` (moved to `quarantined_city_rates.csv`). |

**Change inventory (largest):**
- `city_parser.py` +502/−166
- `bullion_service.py` +412/−209
- `persistence.py` +302/−123
- `gold_impact.py` +288/−91
- `data_service.py` +263/−204
- `news_client.py` +186/−19
- `page.tsx` +316/−176
- New modules: `forecast_engine.py` (680 lines), `mjdta_series.py`, `news_features.py`, `provenance.py`, `archive_audit.py`, `human_review.py`, `ollama/classifier.py`, `kjpl/validator.py`, `kjpl/live_worker.py`, `models/research.py`
- Two migrations: `a7c3e91b42d0`, `c4d912f8a103`
- `deploy/oracle/*`, two frontend components, about 12 docs

**Integrity risks (not defects in the code itself):**
- **R-1.** Pulling `origin/develop` will conflict. The old remote workflows keep appending to `city_rates.csv`/`kjpl_rates.csv`, and locally rows were deleted from those same files.
- **R-2.** The local archive snapshot (3,937 rows) is already behind origin (4,071 rows). The audited CSV and the human-review sample are stale relative to the remote.
- **R-3.** The new collector has **never run**: there is no `data/news/collection_runs.jsonl`, and `daily_research_report.json` shows `collector_v2_runs_count: 0`. "First-seen timestamps collected prospectively" is code, not yet data.

---

## C. Five-city live system

| Check | Result | Evidence |
|---|---|---|
| ID→city mapping 48–52 | **PASS** | `city_parser.py:26-91` |
| ID 47 separate (ALL_INDIA, GOLD_1KG_9999) | **PASS** | `city_parser.py:27-37` |
| Source weight 1g / INR per gram | **PASS** | `weight: 1.0, unit: "1g"` for 48–52 |
| `/100` | Only applied when the raw price is ≥ ₹500,000, i.e. a total-bar quote (`city_parser.py:146-156`), and then bounded by the validator. Not triggered for 1g quotes. | PASS |
| `GOLD_100G_999` naming vs 1g source | The stable FK identity is kept. The 100g value is **display-only** (`bullion_service.py:314,403` multiply per-gram ×100 for display). | PASS, naming debt |
| Known-bad values quarantined | ₹100.0 artifact, 52.82 (USD/oz), and a 1kg total misread as per-gram all return `QUARANTINED` | ad-hoc test via `_build_validated_item` |
| One city cannot modify another | **PASS.** Seeded 5 cities, then updated only Mumbai (13050→13999). The other 4 kept their price and `last_verified_at`. | adversarial test on SQLite via `persist_parsed_payload` |
| 1kg → grams | `validator.py:resolve_weight_grams` maps 1kg→1000 g | PASS |
| API when DB fails | `/health` returns 503 (`main.py:68-79`); production startup fails closed (`main.py:36-39`) | PASS |
| CSV fallback in production | Disabled when `ENVIRONMENT=production` (`bullion_service.py:154,513`) | PASS |

**No regression found in System A from the research work.** Live WebSocket/Oracle behaviour was **NOT VERIFIED** (no live KJPL access).

---

## D. News archive audit (independently reproduced)

`audit_news_archive()` was re-run on the working-tree inputs. The output is **identical row-for-row** to the committed `news_archive_audited.csv`.

| Status | Claimed | Reproduced |
|---|---|---|
| Raw rows | 3,937 | 3,937 |
| SYNTHETIC_FIXTURE | 23 | 23 |
| HISTORICAL_UNVERIFIED_AVAILABILITY | 3,692 | 3,692 |
| VERIFIED_SOURCE | 221 | 221 |
| DUPLICATE | 1 | 1 |
| Language labels | "49 normalized" | 49 raw labels → 48 codes (`en`/`English` merged) |

**Synthetic rule** (`provenance.py:128-139, 249-269`): seed domain AND a bare `-YYYY-MM-DD` slug.
- It correctly caught 22 rows dated 18–28 Sep, plus a 23rd row dated **29 Sep** (`economictimes.../gold-steadies-india-2026-09-29`). That row fits the same seed pattern.
- **Risk:** genuine Reuters URLs end in `-YYYY-MM-DD/`, so a real Reuters article arriving via GDELT would be misclassified as synthetic. No such row exists today. The rule is precise for this archive but not robust going forward.

**VERIFIED_SOURCE first-seen values are not first-seen (HIGH, confirmed):**
- All 221 come from matching against `live_news.csv.ingested_at` (`archive_audit.py:45-64, 141-148`).
- In the code that produced that file (HEAD `news_client.py:695`), each run did `live_pool[cand["canonical_url"]] = cand`. A re-sighted article overwrote its row, so `ingested_at` is the **last** sighting, not the first. This is conservative (no look-ahead), but the provenance label is wrong.
- All 221 timestamps fall on just 9 distinct run minutes (8–10 Nov).
- 3 rows matched **by title only**. These include generic daily headlines ("Gold Rate Today: Check 22K, 24K…"); one, published 2 Oct, was stamped with a 9 Nov first-seen (914 h). That timestamp belongs to a *different* article.
- The match is deterministic for fixed inputs, **not** for fixed archive content. `live_news.csv` is a rolling 72 h file, so re-running the audit later changes the VERIFIED set.

**Unverified exclusion:** confirmed. `news_features.py:113-114` requires `VERIFIED_SOURCE`, and test T4 (below) shows unverified injections have no effect.

---

## E. News collector audit (new code)

| Check | Result | Evidence |
|---|---|---|
| First-seen set on genuine first observation (audited archive) | **PASS**: two sightings 6 h apart keep t1 | adversarial test via `save_news_datasets` |
| Repeat collection doesn't reset first-seen | PASS for the audited archive. The live file keeps t1 in the test, but that depends on a sort tie-break (`news_client.py:832` still overwrites the pool entry). | LOW risk |
| Publication vs collection kept separate | PASS | `news_client.py:687-705` |
| First-seen durability | **Only** in `news_archive_audited.csv`, and only if that file already exists (`news_client.py:751-799`). The raw archive still writes 5 columns. The audited file is **untracked** today. | MEDIUM |
| Recurring headlines dropped forever | **Confirmed defect.** The archive dedup compares against *all-time* normalized titles (`news_client.py:749,763`). A new article with a new URL two days later and the same headline is never archived. | MEDIUM |
| Collection status semantics | SUCCESS / PARTIAL_FAILURE / NO_NEW_NEWS / FAILED are distinguished (`collect_news_csv.py:38-45`) | PASS |
| Run log persisted | `collection_runs.jsonl`, committed by the workflow. **Never written to Neon**; `NewsCollectionRun` has no writer. | see O |
| Story clustering (`provenance.py:182-228`) | Key = first 6 non-stopword tokens + 48 h UTC bucket. On the real archive: 3,913 eligible → 3,824 clusters, only 76 multi-member. In practice it is **near-exact-headline dedup, not syndication clustering**. False merges are mostly generic daily-rate pages (benign). **3 keys split across a bucket boundary with members under 24 h apart** → a story can count twice in one 24 h window. No future-member leakage: the ID depends only on the article's own title and time. | MEDIUM |

---

## F. Sentiment audit

**What's fixed:**
- Tone and gold impact are separate fields.
- The FinBERT→direction fallback is **removed** from `gold_impact.py`. Unmatched headlines become `UNKNOWN` (1,470 of 2,405 English eligible rows).

**Confirmed classification defects on real archive headlines** (`gold_impact.py:35-68, 319-337`; first match wins):

| Headline (real archive) | Classifier output | Problem |
|---|---|---|
| "Gold Rises As Softer US Inflation Cools October Fed Rate Hike Bets" | **BEARISH** FED_POLICY | Dovish news. `\brate hikes?\b` matches "rate hike bets" with the negation ignored. Wrong sign. |
| "Gold prices rise as softer U.S. inflation data ease Fed rate hike fears…" | **BEARISH** | Same wrong sign |
| "…Gold rises as markets scale back October Fed rate hike bets" | **BEARISH** | Same wrong sign |
| "'Rate cuts off the table': Why RBI hiked repo rate…" | **BULLISH** FED_POLICY | Wrong central bank and wrong sign |
| "Gold Edges Lower After Fed Holds Rates With Limited Guidance" | BEARISH HIGH confidence, surprise UNKNOWN | A hold labelled hawkish with no evidence about expectations (14 such rows) |
| "Dubai gold prices drop further ahead of Indian festivals…" | BULLISH INDIAN_PHYSICAL_DEMAND | A price report labelled as a demand driver |

- **Surprise is detected but never used** to set direction, and almost never fires: 3/2,405 rows have a non-UNKNOWN surprise. Direction for Fed holds and inflation is asserted without expectation evidence, which the protocol forbids.
- **Uncertainty is forced into MIXED:** "ahead of Fed", "Fed meeting", any "crude"/"CPI" mention → MIXED (145 such rows; `gold_impact.py:67-80, 425-435`). These should be UNKNOWN.
- **PRICE_REPORT under-detects:** it is checked only *after* every macro rule (`gold_impact.py:437`). 493 headlines describe a gold price move but are not flagged; 103 of them are labelled BULLISH/BEARISH and **enter the primary features**.
- **Legacy conflation remains:** `/api/news/summary` counts `sentiment_label in ("positive","bullish")` as one ratio (`api/routes/news.py:235-236`). The legacy ML pipeline (still run by `pipeline-update.yml`) uses FinBERT `sentiment_mean_1d` features.
- **Ollama** (`ollama/classifier.py`):
  - Strict Pydantic validation; raises on bad output (no fabricated fallback); temperature 0; prompt version recorded; optional and not required by CI.
  - **Not wired anywhere** (no callers).
  - The model is a mutable tag (`qwen3.5:4b`), not a digest; no retry; no token limit (`num_predict`); `format: "json"`, not a JSON schema; the health check matches substrings; nothing persists labels or label timestamps.
  - Live daemon/model availability: **NOT VERIFIED**. Your Mac's `localhost:11434` isn't reachable from the audit environment.

---

## G. Human validation audit

- `human_review_sample.csv` has 250 rows, all English, all eligible (218 HISTORICAL_UNVERIFIED, 32 VERIFIED), no duplicate clusters. Human columns are 0/250 non-blank. Regeneration is deterministic.
- Kappa formula, confusion matrix and the pending gate are correct (`human_review.py:231-261`).
- **HIGH, confirmed:** `python scripts/review_news_labels.py` with no flags runs **export + evaluate** (`review_news_labels.py:29-31`). Export rewrites the CSV with blank human columns (`human_review.py:147-161`). I added a test label in a scratch copy, ran the default command, and the **label was erased**.
- **Anchoring bias:** predicted labels and rationale sit next to the blank human columns, so annotators see the model's answer.
- **Sampling bias:** the sample is stratified on *predicted* class. UNKNOWN is 10% of the sample but 61% of the population, so accuracy and κ must be reweighted by stratum. False negatives (human directional, model UNKNOWN) are barely sampled.
- Invalid human labels are silently skipped, not rejected or counted. Absent-class precision/recall returns 0.0 instead of undefined. Driver and surprise human labels are collected but never scored. `min_reviewed=20` gates "EVALUATED".

**Recommended protocol:**
- Blind the predictions (separate files joined by `sample_id`).
- Use two annotators and report inter-annotator κ.
- Follow written definitions for UNKNOWN/MIXED/NEUTRAL/PRICE_REPORT.
- Report stratum-weighted metrics.
- Freeze the sample under a version name and never re-export over it.

---

## H. MJDTA target audit

- **Reproduced:** 47 raw rows → 45 eligible, 2 excluded. `STALE_REPEAT_CARRYOVER` is 20 Sep (a Sunday repeat of Saturday's 09:29 publication). `UNCERTAIN_SOURCE_DATE` is 1 Nov (Sunday, clock-only).
  - The claim "2 Sunday anomalies" is approximately right: both are Sundays, but under two different rules.
  - The claim "47 raw records preserved" is inaccurate: the HEAD file had **54** rows. 6 intra-day evening re-observations were moved to `quarantined_kjpl_rates.csv` (preserved byte-identical); the earliest observation was kept, which is correct.
- **Spec consistency:** `MJDTA_SPEC` = MJDTA_GOLD_24K / EXCL_GST / 0.999 / INR_PER_1G (`mjdta_series.py:16-22`), used throughout. Values ₹12,775–14,285. The forecast path reads no city or external price.
- **Timestamps:** `available_at_utc = observed_at_utc` (conservative). The publication date is inferred from the observation's IST date (`mjdta_series.py:132-136`); that's wrong when the collector observes after midnight, but it isn't used for gating.
- **Gaps:** 7 calendar days are missing (Sundays plus 31 Oct). The series still carries no explicit publication date.
- **What 45 observations can support:** pipeline correctness and descriptive statistics only. A daily-change SD of about 0.86% and lag-1 autocorrelation of about 0.19 (computed earlier) mean that no model comparison at this size can reach significance unless the effect is very large. Complex ML is not defensible.

---

## I. Feature-generation audit (`news_features.py`)

| Item | Finding |
|---|---|
| Formulas | `n_clusters_relevant` = non-price-report clusters (incl. MIXED/NEUTRAL). `net_impact = (bull − bear)/(bull + bear + unknown)`, with MIXED/NEUTRAL excluded from the denominator. `unknown_share = unknown/non_price_total`. Zero denominator → `net_impact = 0.0`, `unknown_share = 1.0` (`:162-166`). |
| Clusters counted once | Within a window, yes (rep per `story_cluster_id`, `:128-137`), apart from the bucket-boundary split in E. |
| `first_seen_at <= T` | Enforced (`:116-125`). Test T2 passes. |
| `label_created_at <= T` | **Enforced on a meaningless value.** The loader recomputes every label with the *current* rules and sets `label_created_at = first_seen_at` (`:228-245`). Test T5: flipping the rules after the fact changed net_impact at a past cutoff from +0.0851 to −0.0851. **CRITICAL.** |
| Coverage | `coverage_ok = not(all runs FAILED and 0 clusters) and clusters ≥ 2` (`:189-191`). **T6:** every run in the window FAILED but earlier clusters exist → `coverage_ok = True` (partial collection looks covered). **T7:** a successful run on a quiet day with fewer than 2 clusters → `coverage_ok = False` ("no news" treated as "no data"). With no run log at all (today's state), status is `NO_RUN_RECORDED` and coverage is still OK. |
| Missing vs zero | The snapshot keeps `coverage_ok`. But the model vector imputes `[0, 0, 1, 0]` (`forecast_engine.py:314-316`), and NEWS_ONLY predicts **0.0 (neutral)** when coverage fails. That is exactly the "missing treated as neutral" pattern. |
| Timezones | All UTC-aware (`parse_utc_iso`, `_to_utc`). PASS. |

---

## J. Forecast mathematics (`forecast_engine.py`)

- **Target:** `log(P[i+h]/P[i])`, with h counted in eligible MJDTA publications (`:337-350, 404-440`). Sign is correct; price = `p0·exp(pred)`. **PASS.**
- **No future data in training:** pairs `j→j+h` require `j+h ≤ i` (`:345`). There is no scaler (so no scaler leakage) and alpha is fixed (so no tuning leakage). T1 (truncate future prices → 200 forecasts unchanged) **PASS**.
- **Same origins for every arm:** every (h, origin) yields all 4 arms. This is achieved by **substitution**: NEWS_ONLY := 0.0 and HYBRID := PRICE_ONLY when coverage fails (`:377-395`).
- **The arms are not meaningful models today (HIGH):**
  - **PRICE_ONLY:** unscaled features (std 0.004–0.017) with ridge α=5 → slope weights about 1e-4 (OLS would give 0.40/−0.21/−0.10/0.76). Predictions span −0.1521% to −0.1497%: effectively the **training-mean drift**.
  - **NEWS_ONLY:** 38/40 origins = 0.0; the other 2 use a hand-set prior `0.002·net_impact·clarity` (`:386`).
  - **HYBRID:** = PRICE_ONLY at 38/40; otherwise `0.75·price + 0.25·news` (`:395`).
  - Warm-up `0.10·ret_1` (`:375`), the ±10% clamp and the blend weights are **not pre-registered** in `EXPERIMENT_PROTOCOL_V1.md`.
  - The protocol's "logistic direction head" does not exist; `up_probability = sigmoid(pred/ret_scale)` (`:364, 416`) is uncalibrated.
  - The asymmetric regularization (tiny price features vs O(1) news features under the same α) would bias any future HYBRID-vs-PRICE comparison.
- **Arm metrics mix arms and statuses (HIGH):** `_aggregate_arm_metrics` (`:194-232, 469-474`) ignores per-forecast status. Real data: NEWS_ONLY h1 shows `EVALUATED`, n=39, MAE ₹87.31 — those are essentially NO_CHANGE's errors. NO_CHANGE "directional accuracy 10.3%" is meaningless (it always predicts FLAT).
- **h=3 non-overlap:** `(i−5) % 3 == 0` (`:460`), applied to the DM input but not to the headline arm metrics, which are reported over overlapping origins.
- **Retrospective generation:** each call regenerates forecasts for **every** historical origin from current data (`:325-462`). These are walk-forward backtests labelled "shadow".

---

## K. Statistical audit (DM / HAC)

- **Arithmetic:** `compute_diebold_mariano` (`:141-191`) is d = L_A − L_B on squared log-return error, Newey-West with Bartlett weights and bandwidth h−1, normal two-sided p-value. It reproduces an independent implementation exactly at n=20/25/40, h=1/3.
- **No small-sample correction (MEDIUM):** without the Harvey-Leybourne-Newbold factor and t(n−1) reference, p-values are anti-conservative. Example: n=20, h=3 gives p=0.072 (code) vs 0.132 (HLN).
  - **Correction:** `DM* = DM·sqrt((n+1−2h+h(h−1)/n)/n)` and `p = 2·(1 − F_t,n−1(|DM*|))`.
- **Double treatment at h=3:** the code subsamples non-overlapping origins *and* applies HAC lag 2. Pick one. Subsampling needs about 60 origins to reach the n=20 gate.
- **Gates:** `MIN_DM_SAMPLES=20` vs `MIN_EVALUATION_SAMPLES=30`. Neither is a power calculation. At n=20–30, DM can only detect very large loss differences.
- **Mislabelled comparison:** `hybrid_vs_no_change` (h1, n=39, p=0.75, COMPUTED) is in substance PRICE_ONLY vs NO_CHANGE.
- **Missing comparisons:** NEWS_ONLY vs NO_CHANGE and PRICE_ONLY vs NO_CHANGE.
- **Degenerate case:** a constant non-zero loss differential returns `p = 1.0` (`:173-180`). It should be flagged degenerate, not "no difference".
- **Recommendation:** keep everything **descriptive** until the pre-registered sample size is reached.

---

## L. Temporal leakage matrix

| Scenario | Tested? | Result | Evidence |
|---|---|---|---|
| Future MJDTA observations alter past forecasts | Yes (T1) | **PASS** (0/200 changed) | prefix truncation via `evaluation_cutoff` |
| Target in rolling features | Code review | PASS | `build_mjdta_price_features` uses `[:i+1]` |
| Stale carried-forward price | Yes | PASS | `STALE_REPEAT_CARRYOVER` excluded |
| Published < T but first-seen > T | Yes (T2) | **PASS** | injected 10 strong-signal articles; no change |
| Label created > T | Yes (T3) | PASS *for injected records only* | — |
| Labels rewritten retroactively | Yes (T5) | **FAIL** | `news_features.py:228-245`; net_impact sign flip |
| Unverified historical articles | Yes (T4) | **PASS** | — |
| Future story-cluster members | Code review | PASS | ID depends only on the article's own title and time |
| Retrospective title matching | Yes | **FAIL (provenance)** | 914 h title-only match (D) |
| Scaler / feature selection / hyperparameter leakage | Code review | PASS (none exist) | — |
| Persisted forecast overwritten after target known | Yes (PG) | PASS: immutable, insert-if-absent | second persist inserts 0 |
| Forecasts created after target known | Yes (PG) | **FAIL**: 304/304 | `persist_research_shadow_results` (`:573-680`) |
| Re-run changes reported history | Yes | **FAIL**: the API recomputes in memory; a changed model writes 0 rows to the DB, so the DB and the API diverge | `predictor.py:162-170` |
| Feature snapshot rebuilt with later information | Yes | **FAIL**: snapshots are recomputed on every call | T5 |

---

## M. Neon / PostgreSQL / Alembic

**Executed against a local PostgreSQL 16.15** (not Neon):
- `alembic upgrade head` → `c4d912f8a103`, rc=0
- `alembic check` → "No new upgrade operations detected"
- `downgrade base` → `upgrade head` → re-run upgrade: all rc=0
- `timestamptz` and `Numeric(14,2)` confirmed
- `features_json` is `json`, not `jsonb` (acceptable)

**Live Neon: NOT VERIFIED** (no credentials used).

**Confirmed defects:**
- **Silent SQLite fallback.** My first Alembic run had a driver problem in the audit container. `build_engine` caught it, fell back to SQLite (`Context impl SQLiteImpl`), migrated the wrong database, and **exited 0** (`session.py:72-95`). The fallback only fails closed when `ENVIRONMENT=production`, and **`kjpl-collector.yml` never sets ENVIRONMENT** (`:43-58`). A missing or broken `NEON_DATABASE_URL` therefore makes CI write MJDTA to an ephemeral SQLite file and report success, with the CSV mirror off. **HIGH.**
- **Dead tables.** `news_articles`, `news_labels`, `news_clusters` and `news_collection_runs` have **no writer anywhere**.
- **Missing fields.** `ForecastRun` lacks model/code version, feature hash, training-window bounds and a `is_backfill`/`created_before_target` flag. `forecast_id` hashes only (protocol, arm, h, origin), so a model change under the same protocol is silently skipped. `ForecastEvaluation` lacks an evaluation version and an FK to the target observation. `news_labels` has no uniqueness or immutability constraint.
- **Migration hides drift.** `c4d912f8a103` upgrade is conditional on `table not in existing`, so it silently skips a pre-existing table even if its schema differs.

---

## N. API / frontend

- `/api/predictions/research-shadow` returns the in-memory recomputation, not persisted records.
- Target identity is shown (MJDTA_GOLD_24K, EXCL_GST, 0.999, INR/1g). The insufficient-sample gate banner is shown.
- **Misleading:**
  - Column header **"P(UP) CALIBRATED"** (`MjdtaPredictionPanel.tsx:211`) labels an uncalibrated sigmoid.
  - Title "**Strict Out-of-Sample Shadow Arms**" (`:134`) describes retrospective backtests.
  - "Coverage: VERIFIED_OK" appears when no collector run was ever recorded.
  - The metrics table shows NEWS_ONLY as EVALUATED with MAE/accuracy.
- The legacy `/api/predictions/latest` still advertises `model_version: "xgboost-v1"` (`predictor.py:151`), though no model exists.

---

## O. Workflows and operations: full lifecycle trace

**News:** GDELT/RSS → `collect_news_csv.py` (GitHub Actions) → CSV + `collection_runs.jsonl`, **committed to git** (auto-commit still present, `news-collector.yml:43-77`) → **not written to Neon** → classification **recomputed at read time** → features in memory → forecasts **computed on API request** → evaluation in memory.

**MJDTA:** KJPL → `collect_kjpl_csv.py --mjdta-only` → Neon only. `ENABLE_CSV_MIRROR=false` and `contents: read` (`kjpl-collector.yml:21-22, 47`) → `kjpl_rates.csv` **is never updated** → the forecast engine reads only that CSV (`forecast_engine.py:545, 562`). **Broken link (CRITICAL).**

**Forecast scheduling:** nothing schedules `run_shadow_forecast_pipeline` or `persist_research_shadow_results`. No workflow, service or job. **Broken link.**

**`pipeline-update.yml`** still runs the legacy ML pipeline, which consumes historical Yahoo-derived `market_rates.csv` (it does not affect the MJDTA target).

**Deployment:** `requirements-api.txt` omits numpy, pandas and xgboost, but `app.main` imports them via `predictor.py:5-6` and `forecast_engine.py:10`. The documented Oracle/docker-compose API (`DEPLOYMENT.md:8`, `docker-compose.yml:34`) **will fail at import**. **HIGH.** The worker's dependencies match `requirements-worker.txt`.

**Free tier / operations:**
- The API recomputes the whole pipeline over 3.9k news rows on every request (no cache).
- The CSV archive grows without bound in git.
- GitHub Actions cron jitter is unchanged.
- SSE / Oracle worker restart behaviour: **NOT VERIFIED.**

---

## P. Test quality

**Command:**
```
cd backend && PYTHONPATH=.:<vendored pure-python deps>:<xgboost stub> python -m pytest tests/ -q --ignore=tests/test_sentiment_analyzer.py
```
**Result:** **123 passed in 8.7 s.** `test_sentiment_analyzer.py` (3 tests) was not run because torch is unavailable. 123 + 3 = the claimed 126.

**Blocker:** no package installs were possible in the audit environment; an `xgboost` import stub was needed because `predictor.py` imports it at module level. The suite left the data CSVs untouched (it only created a scratch SQLite file).

**Gaps:**
- The leakage test builds `EligibleNewsRecord` with an explicit `label_created_at`, which **bypasses the CSV loader** where the back-dating happens.
- The coverage test **asserts NEWS_ONLY = 0.0 as correct**.
- The persistence test uses SQLite `create_all`, not migrations, and doesn't check backfill semantics.
- **No test calls `compute_diebold_mariano`.**
- No PostgreSQL tests. No test of the review-script overwrite. No test of classifier sign on negated phrases. No workflow/lifecycle test.

---

## Q. Findings register

**Confirmed defects:**

| ID | Severity | File and lines | Finding | Evidence | Required action |
|---|---|---|---|---|---|
| F-01 | CRITICAL | `kjpl-collector.yml:21-22,43-58`; `collect_kjpl_csv.py:361-372`; `forecast_engine.py:545,562` | MJDTA target series frozen once deployed | CSV mirror off, no commit, engine reads CSV only | The engine must read MJDTA from Neon (`bullion_rate_observations`/MJDTA table), or CI must persist the CSV durably |
| F-02 | CRITICAL | `forecast_engine.py:325-462,573-680`; `models/research.py:147-185` | Backfilled hindsight forecasts persisted as immutable "shadow" forecasts | PG: 304/304 created after target known | Persist **only the latest origin** at run time; reject `created_at ≥ target time`; add `generation_mode` (BACKTEST/PROSPECTIVE); store backtests in a separate table |
| F-03 | CRITICAL | `news_features.py:228-245` | Labels recomputed on load and back-dated to `first_seen_at` | T5 net_impact sign flip | Persist labels once (append-only `news_labels` with real `label_created_at`, versions); features read stored labels |
| F-04 | HIGH | HEAD `news_client.py:695`; `archive_audit.py:45-64,141-148` | 221 "first-seen" values are last-seen; 3 title-only collisions | code + 914 h example | Rename to `OBSERVED_IN_LIVE_WINDOW`; drop title-only matching; treat them as upper bounds |
| F-05 | HIGH | `gold_impact.py:35-52,319-337` | Wrong sign on negated/dovish Fed headlines; non-Fed banks → FED_POLICY | 3 real dovish headlines → BEARISH; RBI → BULLISH | Negation/"ease/scale back" handling, central-bank entity check, run PRICE_REPORT first, require surprise evidence or output UNKNOWN |
| F-06 | HIGH | `gold_impact.py:67-80,425-435` | Insufficient evidence forced into MIXED | 145 rows | Map to UNKNOWN |
| F-07 | HIGH | `gold_impact.py:437` | Price-move headlines not excluded from features | 493 rows, 103 directional | Detect price-move phrasing before macro rules, or as a co-label |
| F-08 | HIGH | `forecast_engine.py:119-134,366-395` | Arms degenerate (PRICE_ONLY = drift; NEWS_ONLY ≈ 0; HYBRID ≈ PRICE_ONLY); undeclared heuristics | weights ~1e-4; 38/40 equalities | Standardize inside the training window, pre-register α, remove hand priors (emit NO_FORECAST instead) |
| F-09 | HIGH | `forecast_engine.py:194-232,469-474`; panel | Arm metrics count imputed/fallback forecasts; NEWS_ONLY shown "EVALUATED" | real-data output | Compute metrics only on SHADOW_ACTIVE common origins; report coverage counts |
| F-10 | HIGH | `news_features.py:189-191`; `forecast_engine.py:314-316,377-379` | Coverage logic misclassifies failed/quiet windows; missing → neutral 0 | T6/T7 | Coverage requires ≥1 SUCCESS/NO_NEW_NEWS run in the window; quiet ≠ missing; missing → no forecast, and the origin is dropped from all arms |
| F-11 | HIGH | `session.py:72-95`; `kjpl-collector.yml` | Silent SQLite fallback outside production; CI doesn't set ENVIRONMENT | Alembic on SQLite, rc=0 | Fail closed whenever `DATABASE_URL` is set; set `ENVIRONMENT=production` in CI |
| F-12 | HIGH | `requirements-api.txt`; `predictor.py:5-6`; `forecast_engine.py:10` | API dependency set incomplete | import closure | Add numpy/pandas, or lazy-import xgboost and drop the legacy predictor from the API |
| F-13 | HIGH | `review_news_labels.py:29-39`; `human_review.py:147` | Default command erases human annotations | reproduced | Never overwrite; export to a new versioned file; `--export` requires `--force` |
| F-14 | MEDIUM | `forecast_engine.py:141-191` | No HLN small-sample correction; double overlap treatment; degenerate p=1 | numeric comparison | Apply HLN + t(n−1); choose subsampling or HAC |
| F-15 | MEDIUM | `news_client.py:749,763` | Recurring headlines never archived | adversarial test | Dedup by canonical URL + (title, date) |
| F-16 | MEDIUM | `provenance.py:182-228` | Bucket-boundary split double counts; near-exact dedup only | 3 real splits | Rolling-window clustering keyed on first-seen, or a sliding merge across adjacent buckets |
| F-17 | MEDIUM | `human_review.py:39-171` | Anchoring and stratum bias; invalid labels skipped | sample: UNKNOWN 10% vs 61% | Blind file, weighted metrics, report invalid counts |
| F-18 | MEDIUM | `MjdtaPredictionPanel.tsx:134,211` | "P(UP) CALIBRATED", "Strict Out-of-Sample" labels | source | Relabel: "Heuristic P(up), uncalibrated", "Retrospective walk-forward" |
| F-19 | MEDIUM | `models/research.py`; `c4d912f8a103` | Dead news tables; missing version/hash/backfill fields; conditional create hides drift | grep / PG | Add fields and writers; make create unconditional |
| F-20 | LOW | `news.py:235-236`; legacy ML | Tone/direction conflation in legacy summary and legacy pipeline | source | Deprecate or relabel |
| F-21 | LOW | `ollama/classifier.py` | No digest pin, retry, token cap or persistence; unwired | source | Pin digest, `num_predict`, bounded retry, persist versioned labels |
| F-22 | LOW | `MJDTA_TARGET_AUDIT` claims | "47 raw preserved", "2 Sunday anomalies" imprecise | reproduction | Correct the wording |

**Risks (not yet defects):**
- R-1 / R-2 / R-3 (Section B).
- Reuters-style URL false positives in the synthetic rule.
- `live_news.csv` first-seen tie-break.
- Unbounded CSV growth in git.
- Recomputing the full pipeline on every API request.

---

## R. Prioritized remediation plan

**Must fix before Neon integration:**
- F-11: fail closed and set ENVIRONMENT in CI.
- F-12: API dependencies.
- F-19: schema fields and writers. Do this before the first persistence run, so the ledger never contains backfill.
- Push or reconcile the branch (R-1) and stop the old auto-committing workflows on `origin/develop`.

**Must fix before prospective shadow forecasts:**
- F-01: target from Neon.
- F-02: prospective-only persistence and a scheduled job.
- F-03: persisted, timestamped labels.
- F-05, F-06, F-07: classifier corrections, re-validated after human labelling.
- F-08, F-09, F-10: model and coverage semantics.
- F-13: annotation safety.
- Pre-register the corrected protocol (including F-14) **before** the first prospective origin.

**Must fix before production deployment:**
- F-18: UI labels.
- F-15, F-16: collector.
- Response caching for the research endpoint.
- Live Neon and Oracle verification.

**Can improve later:** F-17, F-20, F-21, F-22, Reuters-URL robustness.

---

## S. Final readiness decision

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Is the five-city live terminal safe? | **YES (code)** / NOT VERIFIED (live feed, Oracle) | Section C; isolation test passed |
| 2 | Is the MJDTA target correctly isolated? | **YES** isolated / **NO** for continuity | Section H; F-01 |
| 3 | Is the news pipeline genuinely prospective? | **NO** | F-03, F-04; collector v2 has 0 runs; nothing written to Neon |
| 4 | Is sentiment methodology defensible? | **NO** | F-05, F-06, F-07; 0/250 human labels |
| 5 | Is feature generation leakage-safe? | **NO** | T5 FAIL; F-10 |
| 6 | Is the forecasting mathematics correct? | **PARTIAL**: target/sign/horizon/no-future-training correct; **arms are not meaningful models** | Section J; F-08 |
| 7 | Is the statistical comparison correct? | **NO**: arithmetic correct, but metrics/pairing semantics and small-sample treatment are wrong | F-09, F-14 |
| 8 | Is Neon integration ready? | **NOT VERIFIED** (live), **NO** (blockers F-11, F-19) | PG16 migrations pass |
| 9 | Is prospective shadow forecasting ready? | **NO** | F-01, F-02, F-03, no scheduler |
| 10 | Is production deployment ready? | **NO** | F-12, F-01, R-1 |

---

### Reproduction notes

- **Archive audit:** `audit_news_archive(Path('data/news/news_articles.csv'), Path('data/news/live_news.csv'), out)`. Compare against the committed `news_archive_audited.csv` (0 differing rows).
- **MJDTA audit:** `load_and_audit_mjdta_series(Path('data/kjpl/kjpl_rates.csv'))` → 47/45/2.
- **T1–T7:** call `run_shadow_forecast_pipeline` / `compute_news_features_at_cutoff` with the injected records described in Section L. T5 monkeypatches `news_features.evaluate_gold_impact` to swap BULLISH/BEARISH, then reloads the CSV.
- **PostgreSQL:** local PG 16.15 on a Unix socket. `DATABASE_URL=postgresql://postgres@localhost:55432/vmd?host=/tmp`, then `alembic upgrade head / check / downgrade base / upgrade head`, then `persist_research_shadow_results` twice, plus SQL:
  ```sql
  select count(*) filter (where f.created_at > e.matured_observed_at)
  from forecast_runs f join forecast_evaluations e using(forecast_id);
  ```
- **Review-script overwrite:** set `human_gold_impact` on row 1 of a scratch copy → run `python scripts/review_news_labels.py` → the field is blank.

*Temporary audit files were written outside the repo at `~/dhruv files/gold/_claude_audit_tmp/` (a working-tree tarball, a diff, a status listing, and vendored pure-Python packages). They can be deleted.*
