# VMD Bullion — Second Independent Forensic Audit

**Scope:** verifying Antigravity's remediation of findings F-01 to F-22 from the first audit (2026-11-11).
**Date:** 2026-11-11 (18:40 IST snapshot) · **Auditor:** Claude (independent)
**Method:**
- The local working tree was snapshotted read-only and audited in an isolated container.
- **No repository file was modified, committed, reset, cleaned or pushed.**
- Adversarial tests ran against the real code paths, using **local temporary PostgreSQL 16.15 databases and synthetic fixtures only**.
- **Production Neon was not contacted.**
- Test scripts are attached: `adv_f01_f02.py` and `adv_f03.py`.

---

## 1. Executive verdict

# FAIL — CRITICAL DEFECTS REMAIN

The remediation is substantial and much of it is correct:
- Hindsight-guarded prospective writer.
- Training-only standardization.
- Removal of hand-set priors.
- Comparable-origin metrics.
- HLN/Student-t DM.
- Stored-label replay that no longer rewrites history.
- Fail-closed PostgreSQL.
- A complete API dependency set.
- Overwrite-safe blind review.

But the new database-backed pipeline introduces or keeps defects that would make prospective collection unreliable from day one:

1. **NEW-1 (CRITICAL): news persistence crashes on routine syndicated stories.** Any collection run in which one story cluster contains two articles that get different labels, or a newly seen copy plus a re-sighted copy, raises `UniqueViolation` on `uq_news_label_append_only_version`. The **entire run is rolled back** (articles, labels and the collection-run record are all lost) and the workflow fails. Reproduced on PostgreSQL in 5 of 5 runs.
2. **F-01 (CRITICAL, regression): the MJDTA target is now "next price change", not "next publication".** VALID observation rows are written only when the price changes (`persistence.py:288-370`), and the forecast engine now reads only those rows. On PostgreSQL, 20 daily publications became a 15-point series. This silently redefines h=1/h=3, structurally penalizes NO_CHANGE, and contradicts the protocol.
3. **F-01 (HIGH): ALL_INDIA contamination.** The MJDTA query admits `city_code='ALL_INDIA'` without checking `source_product_id`. A VALID ALL_INDIA `MJDTA_GOLD_24K` row (`source_product_id='GOLD'`, ₹13,431.20) entered the series and **became the prospective forecast origin**.
4. **F-05 not fixed:** the headline cited in the first audit, "Gold rises as softer US inflation cools Fed rate hike bets", is **still BEARISH**.

---

## 2. Repository integrity

| Item | Observed |
|---|---|
| Branch / HEAD | `develop` @ `06fdf0a` (unchanged since audit 1) |
| Working tree | 110 status entries, **0 staged, 0 deleted** |
| Changes since audit 1 | 32 files modified; 4 new: `label_store.py`, migration `d91e4a7b2019`, `scripts/run_prospective_forecast.py`, `data/news/human_review_reference.csv`. **Not changed:** `kjpl/persistence.py`, `collect_kjpl_csv.py`, `news_client.py`, `c4d912f8a103`, legacy `ml/training/*` |
| First audit report | Available (delivered earlier in this conversation; not inside the repo) |
| `git diff --check` | **2 issues:** trailing whitespace at `HANDOFF_TO_CLAUDE.md:3` and `:6` |
| Remote | Still 9+ bot commits behind `origin/develop`; old auto-committing workflows still active on GitHub (R-1 unchanged) |
| Secrets | None tracked or staged |

---

## 3. Critical defect verification

### F-01 — MJDTA database continuity → **PARTIALLY FIXED (critical regression remains)**

**What's now in place:**
- Collection writes to PostgreSQL first, then the forecast step runs (`kjpl-collector.yml:43-58`, same job, sequential).
- The engine reads `bullion_rate_observations` via `load_mjdta_observations_from_db` (`mjdta_series.py:179-224`). It never falls back to CSV and fails closed.
- A new MJDTA record does become the next frontier origin (verified on PostgreSQL).

**Defects:**

| Check | Result | Evidence |
|---|---|---|
| Every publication becomes an observation | **FAIL** | `persistence.py:288-370` inserts a VALID observation only `if price_changed`. PG test: 20 publications (5 repeats) → 15 rows → 15-point series |
| Query selects only the intended MJDTA product | **FAIL** | `mjdta_series.py:186-191` includes `ALL_INDIA`; no `source_product_id == 'MJDTA_GOLD'` check. PG test: ALL_INDIA row (₹13,431.20) entered the series and became the origin |
| GST / purity / unit | PASS by product_id (`MJDTA_GOLD_24K` vs `_GST` are separate) | — |
| Duplicates | Deduplicated only at an identical timestamp (prefers CHENNAI); different timestamps both kept | `mjdta_series.py:194-199` |
| Availability timestamp | `available_at = observed_at` (conservative) | PASS |
| Missing data fails closed | PASS (no CSV fallback); fewer than 6 obs → `INSUFFICIENT_MJDTA_HISTORY` | `forecast_engine.py:936-943` |
| Historical seeding | No MJDTA history is seeded into the DB. A fresh Neon needs ≥16 price changes before PRICE_ONLY can activate. | — |

**Required:**
- Persist one VALID observation per *distinct publication* (keyed on `source_published_at`), changed or not; mark unchanged ones `is_changed=false`.
- Restrict the query to `city_code='CHENNAI' AND source_product_id='MJDTA_GOLD'`.

### F-02 — Prospective vs backtest persistence → **PARTIALLY FIXED**

| Check | Result |
|---|---|
| Backtest rejected by prospective writer | **PASS** (ValueError) |
| Forged old-origin PROSPECTIVE forecast (targets already exist) | **PASS** (rejected: "post-origin observations exist") |
| Target fields null at creation | PASS |
| Idempotent re-run at the same origin | PASS (0 inserted) |
| Evaluation only after maturity; target linkage | PASS (8 evaluations after 3 new publications) |
| **Model-version change** | **FAIL.** `_make_forecast_id` (`forecast_engine.py:118-122`) and the unique constraint (`research.py:176-183`) exclude `model_version`. The new model's forecasts were silently skipped; the ledger shows only `RIDGE_STD_V1`. |
| **DB-level immutability / hindsight guard** | **FAIL.** A direct ORM insert of a hindsight PROSPECTIVE row and an `UPDATE` of a stored prediction were both accepted by PostgreSQL. Guards are application-only. |
| Forecast rows mutated after creation | `evaluate_matured_prospective_forecasts` writes `target_observation_id`/`target_observed_at` back onto `ForecastRun` (`:880-881`) |
| Snapshot hygiene | A new `ResearchFeatureSnapshot` is inserted on **every** run (snapshot_id includes `generated_at`) even when no forecast is inserted. With 6 KJPL runs a day, that's orphan rows. |
| Concurrency | Two workers race to an IntegrityError on the unique constraint (no conflicting rows, but the step fails); no advisory lock |

### F-03 — Immutable news-label provenance → **PARTIALLY FIXED**

| Check | Result |
|---|---|
| Old sign-flip replay: historical feature unchanged | **PASS.** net_impact at T1+1h stayed 1.0 after flipping the rules |
| `label_created_at` = actual classification time | PASS (`collect_news_csv.py:84`) |
| Features read stored labels (DB) | PASS (`news_features.py`, `load_eligible_news_records_from_db`) |
| Identical re-sighting idempotent (single-member clusters) | PASS (0 appended on runs 2–3) |
| **Multi-member clusters** | **FAIL (NEW-1, CRITICAL).** `label_store.py:197-233` queries the "latest" label with `autoflush=False` (`session.py`), so pending labels from the same run are invisible. A second label for the same cluster at the same `label_ts` violates the unique constraint (`research.py:106-112`) and the whole run rolls back. Reproduced: (a) new Reuters copy + re-sighted Mint copy → run failed; (b) two differently worded members → 4/4 runs failed. |
| New classifier version creates a new label | **FAIL.** Rule changes don't bump `SENTIMENT_VERSION` (still `GOLD_SENTIMENT_V2` after the flip). Labels differ only by hash and time; version lineage is lost. |
| Model mixing | The forecast and API call `load_eligible_news_records_from_db` with no `sentiment_version`/`model_name` filter (`forecast_engine.py:950, 1242`). Rule and Ollama labels for a cluster would compete by confidence. |
| Cluster-ID stability across runs | **FAIL.** `assign_story_clusters` seeds the ID with the anchor's timestamp *within the batch*. The same article got `clu2_08d6…` in run 1 and `clu2_fad2…` in run 2. `NewsArticleRecord.story_cluster_id` is insert-only, so articles and labels drift apart. |
| JSONL vs DB | `append_label_to_jsonl` always appends (2 identical calls → 2 lines). CI disables JSONL (`ENABLE_CSV_MIRROR=false`), so this is local-only divergence. |

---

## 4. Findings status matrix (F-01 to F-22)

| ID | Status | Evidence (file:line / test) |
|---|---|---|
| F-01 | **PARTIALLY FIXED** (critical regression) | DB path exists; change-only rows `persistence.py:288-370`; ALL_INDIA `mjdta_series.py:186-191` |
| F-02 | **PARTIALLY FIXED** | Writer guards pass; model_version reuse `forecast_engine.py:118-122`, `research.py:176-183`; no DB immutability |
| F-03 | **PARTIALLY FIXED** | Replay safe; NEW-1 crash `label_store.py:197-233`; no version bump; cluster drift |
| F-04 | **NOT FIXED** | Same 221 `VERIFIED_SOURCE` from last-seen `live_news`; title-only matching unchanged (`archive_audit.py`). These are backfilled to DB as VERIFIED with those first-seen values |
| F-05 | **NOT FIXED** | Negation covers only pause/skip/halt/end/no (`gold_impact.py:55-61`). "…cools Fed rate hike bets", "hike bets fade", "pare bets on Fed rate hikes" → **BEARISH**; "Powell: rate cuts not on the table" → **BULLISH**; "ECB cuts rates; Fed seen holding" → BULLISH FED_POLICY; RBI repo headline still BULLISH FED_POLICY. Archive: 6/10 dovish "hike bets eased" headlines still BEARISH. Surprise detected on 3/2,405 and **never used** ("Fed holds rates steady as expected" → BEARISH; "Fed unexpectedly raises rates" → UNKNOWN) |
| F-06 | **VERIFIED FIXED** | MIXED only on conflicting signals (`gold_impact.py:438-460`); archive MIXED 301 → 7; previews → UNKNOWN |
| F-07 | **PARTIALLY FIXED** | Price-report check now first (`gold_impact.py:293-298, 341`), but `_CAUSAL_MACRO_GUARD_RE` lets "Gold rises as…" through. 489 price-move headlines unflagged, 97 directional (was 493/103). "Gold hits record high on safe-haven demand" → BULLISH GEOPOLITICS |
| F-08 | **VERIFIED FIXED** | Train-only μ/σ (`forecast_engine.py:155-185`); no priors; PRICE_ONLY h1 SD 0.73% (was ~0.002%) |
| F-09 | **VERIFIED FIXED** | Unavailable predictions excluded; `paired_comparable_origins` over 4-arm common set (`:400-470`); real-data paired n=0 reported honestly |
| F-10 | **PARTIALLY FIXED** | No runs / all failed / partial below 50% → `coverage_ok=False`, `net_impact=None` (8 scenarios tested). But a **healthy** run with 0–1 clusters is also "unavailable", so news arms are scored only on news-heavy days (selection bias) |
| F-11 | **VERIFIED FIXED** | Bad PG URL raises in dev/prod/`REQUIRE_POSTGRES`; empty URL + `REQUIRE_POSTGRES` raises (`session.py:72-90`); workflows set `REQUIRE_POSTGRES=true` |
| F-12 | **VERIFIED FIXED** | `app.main` import closure fully covered by `requirements-api.txt` (no xgboost import) |
| F-13 | **VERIFIED FIXED** | Default, `--export` and `--export --overwrite` all refuse when human labels exist (FileExistsError); label preserved |
| F-14 | **PARTIALLY FIXED** | HLN + t(n−1) matches an independent implementation exactly (n=20/31/45, h=1/3). Still: h=3 = non-overlap subsample **plus** HAC lag 2 **plus** HLN(h=3) (double correction, `:430-450`); NaN loss → `COMPUTED`, p=1.0; constant non-zero differential mislabelled `DEGENERATE_IDENTICAL_PREDICTIONS` |
| F-15 | **PARTIALLY FIXED** | DB path dedups by canonical URL, so a recurring headline with a new URL is stored. CSV path (`news_client.py:749,763`) unchanged (disabled in CI) |
| F-16 | **PARTIALLY FIXED** | Midnight split fixed. **New:** `compute_story_cluster_id` has **no time component** (`provenance.py:241-243`; same headline 90 days apart → same ID), used by fallbacks in `label_store.py:113,353` and `gold_impact.py`. Anchor `latest_dt` extension chains daily bulletins (Nov 5/6/7 → one cluster). Cross-run ID instability (see F-03) |
| F-17 | **PARTIALLY FIXED** | Blind sheet has no predictions; separate reference file; stable IDs; deterministic. No sampling weights in evaluation; invalid labels (`bullishh`) still silently skipped |
| F-18 | **PARTIALLY FIXED** | Panel shows PROSPECTIVE vs "BACKTEST DIAGNOSTIC ONLY", UNAVAILABLE, paired N. But `latest_forecasts` falls back to backtest forecasts when the ledger is empty (`forecast_engine.py:1258-1261`); the protocol and code still call `up_probability` "calibrated" (`EXPERIMENT_PROTOCOL_V1.md:28`, `forecast_engine.py:164`) with no calibration evidence |
| F-19 | **PARTIALLY FIXED** | Research tables now have writers; label uniqueness constraint added (and causes NEW-1). No DB immutability; `c4d912f8a103` still has 7 conditional `not in existing` creates; no migration step in any workflow |
| F-20 | **PARTIALLY FIXED** | `/api/news/summary` now uses gold_impact. Legacy `walk_forward_evaluation.py` (unchanged) still uses FinBERT `sentiment_mean_1d` and runs in `pipeline-update.yml` |
| F-21 | **PARTIALLY FIXED** | Digest resolved and persisted (truncated to 32 chars), prompt version, strict parsing. `classify_and_persist` has **no caller**; no retry, no `num_predict`, no JSON schema. Live daemon: **NOT VERIFIED** |
| F-22 | **PARTIALLY FIXED** | The protocol contradicts the code: "next valid distinct publication" (code = next price change); "ALL_INDIA never enters MJDTA targets" (query admits ALL_INDIA); "modifying classifiers creates new rows" (no version bump); "calibrated" probabilities. Protocol not hash-frozen |

**Tally:** 6 verified fixed · 13 partially fixed · 2 not fixed · 1 not verified (live Ollama, under F-21).

---

## 5. Newly discovered defects

| ID | Severity | Location | Finding | Reproduction |
|---|---|---|---|---|
| NEW-1 | **CRITICAL** | `label_store.py:197-233`; `research.py:106-112`; `session.py` (`autoflush=False`) | Label append raises UniqueViolation for multi-member clusters; the whole run rolls back | `adv_f03.py` / inline test: run 1 Mint copy; run 2 Reuters copy + Mint re-sighting → `IntegrityError`; rows unchanged |
| NEW-2 | **CRITICAL** | `persistence.py:288-370` + `mjdta_series.py:179` | Target series = price changes only | `adv_f01_f02.py`: 20 publications → 15 obs |
| NEW-3 | HIGH | `mjdta_series.py:186-191`; `forecast_engine.py:756-764` | ALL_INDIA MJDTA rows admitted; no `source_product_id` filter | ALL_INDIA row became origin |
| NEW-4 | HIGH | `provenance.py:241-243` | Time-less cluster ID fallback | Same title 90 days apart → same ID |
| NEW-5 | HIGH | `provenance.py` `assign_story_clusters` | Cluster IDs not stable across runs; insert-only article rows → article/label cluster drift | Same article: different IDs in runs 1 and 2 |
| NEW-6 | MEDIUM | `forecast_engine.py:950,1242` | No label version/model filter at forecast time | Code review |
| NEW-7 | MEDIUM | `forecast_engine.py:960-990` | New snapshot row every forecast run regardless of insertion | PG: 2 snapshots for 1 forecast set |
| NEW-8 | MEDIUM | `test_gold_impact_and_live_signal.py::test_prediction_status_includes_news_intelligence`; `predictor.py` | Test passes only when a previous run left a populated `data/goldsense.db`; on a clean DB `/api/predictions/latest` raises `OperationalError` (HTTP 500), not `UNAVAILABLE` | Isolated run fails 1/1; second full run passes |
| NEW-9 | LOW | `HANDOFF_TO_CLAUDE.md:3,6` | `git diff --check` trailing whitespace | `git diff --check` |

---

## 6. Adversarial test results

| Test | Result |
|---|---|
| Bad / missing PG URL in dev, prod, `REQUIRE_POSTGRES` | Fails closed (4/4) |
| 20 publications with 5 repeats → series length | **15** (FAIL) |
| ALL_INDIA plausible MJDTA row | **Enters series; becomes origin** (FAIL) |
| New record → next frontier origin | PASS |
| Backtest into prospective writer | Rejected (PASS) |
| Forged hindsight forecast via writer | Rejected (PASS) |
| Direct ORM hindsight insert / UPDATE of prediction | **Accepted by DB** (FAIL) |
| Model-version change | **Silently skipped** (FAIL) |
| Maturation and evaluation | 8 evaluations, correct targets (PASS) |
| Rule flip → historical feature | Unchanged (PASS) |
| Identical re-sighting | Idempotent (PASS) |
| Syndicated / two-member cluster runs | **Run fails, rollback** (FAIL ×5) |
| Coverage: none / failed / partial 4/11 / partial 9/11 / zero / one / three / dup / unlabelled | Correct, except quiet-day = unavailable |
| Required 9 headlines + 24 counterexamples | 7 wrong-sign or wrong-driver cases (see F-05) |
| Human review overwrite (3 invocations) | Refused (PASS) |
| DM vs independent HLN | Exact match (PASS); NaN/constant edge cases FAIL |
| Clustering: midnight / 37 h / reworded / boilerplate / daily bulletins / chain | Midnight PASS; bulletins chained across 3 days; reworded split |

---

## 7. PostgreSQL verification status

**Local PostgreSQL 16.15:**
- `alembic upgrade head` → `d91e4a7b2019` rc=0
- `alembic check` → no drift
- `downgrade base` → `upgrade head` rc=0
- All F-01/F-02/F-03 integration tests ran on PG

**Live Neon: NOT VERIFIED.**

Not covered by the repo's own tests: the repo's PG test only checks connection failure (`test_f11_…`); none of the persistence tests run on PostgreSQL.

---

## 8. Frontend verification

| Check | Result |
|---|---|
| ESLint (`node node_modules/eslint/bin/eslint.js . --no-cache`, on your machine) | rc=0 |
| `tsc --noEmit --incremental false` | rc=0 |
| `next build` | **NOT VERIFIED.** Only `@next/swc-darwin-arm64` is installed and the audit shells are Linux. Run on the Mac with `npm run build`. |

Label issues are listed under F-18.

---

## 9. Workflow lifecycle verification

**KJPL path:** KJPL → MJDTA persist (Neon, `REQUIRE_POSTGRES`) → `run_prospective_forecast.py` in the same job (sequential; a failed collection skips forecasting).
- **Broken semantics:** unchanged publications never reach the series (NEW-2).

**News path:** GDELT/RSS → `collect_news_csv.py` → Neon (`contents: read`, no commits, CSV/JSONL off).
- **Broken:** NEW-1 crashes the run on syndicated clusters.

**Migrations:** no workflow runs `alembic upgrade`, so Neon schema state is manual. There's no concurrent-migration risk, but also no guarantee the tables exist.

**Ordering:** news (03/09/15/21 UTC) and KJPL (00:38–08:38 UTC) are independent schedules. The forecast uses whatever labels exist at `generated_at` (correctly gated).

**Other:**
- `run_prospective_forecast.py` returns 0 even when the report status is degraded.
- The daily report is written to the ephemeral runner only.
- Legacy `pipeline-update.yml` still runs the FinBERT/Yahoo-CSV ML pipeline.

---

## 10. Remaining operational blockers (must fix before prospective collection)

1. **NEW-1:** flush before the latest-label lookup (or dedupe labels per cluster in memory per run), and decide what one label per cluster per run means.
2. **NEW-2 / F-01:** one observation per distinct publication.
3. **NEW-3:** restrict to CHENNAI + `source_product_id='MJDTA_GOLD'`.
4. **F-05:** fix the negated/dovish phrasing families, add central-bank identity, use surprise for direction. Then complete the human reference labels before relying on the labels.
5. **NEW-4 / NEW-5:** stable, time-bounded cluster identity persisted across runs.
6. **F-02:** `model_version` in `forecast_id` and the unique constraint; DB triggers or revoked UPDATE/DELETE on ledger tables.
7. Add `alembic upgrade head` as a guarded, single-concurrency step, and run the persistence tests on PostgreSQL in CI.

---

## 11. Final readiness decision

| Question | Answer |
|---|---|
| Five-city terminal safe? | YES (unchanged since audit 1) |
| MJDTA target correctly isolated? | **NO** (ALL_INDIA admitted) |
| MJDTA target correctly defined? | **NO** (price changes only) |
| News pipeline prospective and durable? | **NO** (NEW-1 run failures) |
| Sentiment defensible? | **NO** (F-05; 0/250 human labels) |
| Feature generation leakage-safe? | **YES for stored-label replay**; label lineage incomplete |
| Forecast mathematics correct? | YES (arms, standardization, targets), given the series definition |
| Statistical comparison correct? | PARTIAL (HLN correct; h=3 double correction, NaN handling) |
| Neon integration ready? | **NOT VERIFIED** live; blocked by items 1–3 and 7 |
| Controlled prospective shadow collection ready? | **NO** |
| Production deployment ready? | **NO** |

**Verdict: FAIL — CRITICAL DEFECTS REMAIN.**

---

### Test execution record

- **Backend:**
  ```
  cd backend && PYTHONPATH=.:<vendored deps> python -m pytest tests/ -q --ignore=tests/test_sentiment_analyzer.py
  ```
  - Clean DB: **1 failed, 122 passed**
  - With leftover DB: 123 passed
  - FinBERT tests (3) not run: torch unavailable, no installs possible
- **Frontend:** ESLint rc=0, `tsc` rc=0, build NOT VERIFIED.
- **Migrations:** upgrade, check, downgrade and upgrade on PG16 all rc=0.
- **Workflows:** all 4 YAML files parse; triggers and permissions inspected. `actionlint` not available.
- **`git diff --check`:** 2 trailing-whitespace issues.
- **Temporary audit files:** `~/dhruv files/gold/_claude_audit_tmp/second/` (outside the repo; safe to delete).
