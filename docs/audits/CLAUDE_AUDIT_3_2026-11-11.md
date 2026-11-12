# VMD Bullion — Third Independent Forensic Audit

**Scope:** verification of Antigravity's second remediation (NEW-1 to NEW-9 and F-01 to F-22).
**Date:** 2026-11-11 (snapshot 20:07 IST) · **Auditor:** Claude (independent)
**Constraints honoured:**
- Read-only snapshot of the local working tree.
- No commit, push, pull, fetch, reset or clean on your repo.
- No source, test or data changes.
- Production Neon was never contacted, and no production collection was started.
- All database tests used **fresh disposable PostgreSQL 16.15** databases with synthetic fixtures.

**Attached evidence:**
- `adv_f01_f02.py` and `adv_f03.py` (Audit #2 scripts, rerun **unchanged**)
- `adv3_ingest_ledger.py` and `adv3_clusters.py` (new attacks for this audit)

**No separate remediation report** exists in the tree; `docs/data/REMEDIATION_REPORT.md` is unchanged since Audit #2. The changes are reflected in `docs/ml/EXPERIMENT_PROTOCOL_V1.md` and in the code, and this audit was done against the code.

---

## 1. Executive verdict

# CONDITIONAL PASS — specific bounded issues remain

All three critical defects from Audit #2 are resolved and reproduced as fixed:
- **NEW-1:** syndicated clusters no longer crash the run.
- **NEW-2:** every distinct publication is now an observation.
- **NEW-3:** the target is isolated from ALL_INDIA, other cities, wrong source IDs and GST rows.

Both original adversarial scripts now pass unchanged. Ledger immutability is enforced in the database for PROSPECTIVE forecast rows. Cluster identity is stable across runs. F-04 provenance is honest. DM edge cases are handled.

The issues below are bounded and none breaks normal operation, but **each must be closed before deployment preparation is considered complete**:

1. **DB guard bypass (HIGH):** a BACKTEST row can be `UPDATE`d into `generation_mode='PROSPECTIVE'`. The hindsight trigger fires only on INSERT, so a hindsight forecast can enter the prospective ledger via SQL. `forecast_evaluations` and `news_labels` have **no** DB immutability (UPDATE and DELETE accepted). `TRUNCATE` wipes the ledger.
2. **Clock-only timestamp fallback (MEDIUM-HIGH, conditional):** when KJPL supplies only "09:29 am", the parser stamps today's date with no future-time guard. Replaying the real 19/20/21 Sep rows put the Sunday carryover back into the series, and a 06:08 IST poll creates a phantom observation dated 3h21m in the future. The current live page appears to supply a full timestamp, so this path is a fallback, not the default.
3. **Residual sentiment errors (MEDIUM):** a few wrong-sign families remain; price-report detection is coarse in both directions; human validation is still 0/250.
4. **Ollama path (MEDIUM, disabled by default):** not idempotent, and one DB error poisons the session for the rest of the run, silently.
5. **Operational:** concurrent migrations across two workflow groups with no lock; 10 research tests removed and 6 consolidated; `next build` not verified; the old auto-committing workflows are still live on GitHub.

---

## 2. Repository integrity

| Item | Observed |
|---|---|
| Branch / HEAD | `develop` @ `06fdf0a` (unchanged since Audit #1) |
| Staged | **None** |
| Working tree | 111 status entries (60+ modified, 51 untracked files incl. new migration `e8b3c1d45207`); no deletions; no stash |
| Changes since Audit #2 | 26 files changed + 1 new migration (label_store, persistence, mjdta_series, forecast_engine, news_features, gold_impact, provenance, news_client, archive_audit, human_review, ollama/classifier, predictor, models/research, 2 workflows, panel, tests, data, docs) |
| `git diff --check` | **rc=0, clean** (Audit #2's whitespace issues fixed) |
| Remote divergence | The local `origin/develop` ref is stale (`06fdf0a`). GitHub `develop` is at `8c98109` (2026-11-11 10:29 UTC), **9 commits ahead**: bot data commits from the **old, still-active auto-committing workflows**. These will conflict with locally modified/quarantined CSVs and still run the old code on schedule. |
| Local dev DB | `data/goldsense.db` (gitignored) is at Alembic `d91e4a7b2019`, **one revision behind head**, and holds 1 real MJDTA row fetched 2026-11-11 09:26 UTC. `docs/operations/DAILY_RESEARCH_REPORT.md` was generated from it. Not Neon. |
| Secrets | None tracked or staged |

---

## 3. Critical defect verification

### NEW-1 — syndicated multi-member persistence → **VERIFIED FIXED**

**Code:**
- `label_store.py:188-232`: DB-stable cluster resolution (existing URL → existing cluster; else a ±36 h open cluster by key or Jaccard ≥ 0.70).
- `label_store.py:330-447`: one deterministic aggregated label per cluster per run, built from *all* stored members, with explicit flushes and a same-timestamp guard.

| Test (PostgreSQL) | Result |
|---|---|
| Audit #2 `adv_f03.py` (unchanged) | All runs succeed; two-member cluster → labels appended `[1,0,0,0]`, history `['MIXED']` |
| New copy + re-sighted copy (run 2) | Succeeds; no rollback |
| Overlapping batches A → A+B → B+C(late, earlier pub) → A?utm / amp/A | **One cluster ID for all**; one label; `n_clusters_relevant=1` (`adv3_clusters.py`) |
| Identical re-sighting | Idempotent (0 appended) |
| Classifier exception for one article | Caught; run persisted as `PARTIAL_FAILURE` with `label_errors` (`label_store.py:449-458`) |

**Residual (LOW):** the open-cluster lookup has no `ORDER BY`, so if two open clusters both match, the database's row order decides. Distinct macro stories with near-identical wording merge (e.g. "…ahead of US CPI" vs "…US PPI"). Daily templated bulletins merge in pairs.

### NEW-2 — publication continuity → **VERIFIED FIXED (full-timestamp path); RESIDUAL RISK on clock-only fallback**

**Code:**
- `persistence.py:411-428`: inserts a VALID observation per distinct `source_published_at`, changed or not, and dedupes repeated polls.
- `persistence.py:222-263`: MJDTA without a source timestamp is quarantined.
- `mjdta_series.py` `load_mjdta_observations_from_db` requires explicit timestamps.

| Test | Result |
|---|---|
| `adv_f01_f02.py` (unchanged): 20 publications incl. 5 unchanged | **20 observations, series 20** |
| 3 polls of one publication | +1 (deduped) |
| Missing timestamp | Quarantined; not in series |
| Same source time, corrected price | +1: **two series points for one publication** (LOW: should supersede, not append) |
| **Replay of real `kjpl_rates.csv` 19/20/21 Sep ("Time : 09:29 am" each day, Sun = Sat carryover)** | **DB path: 3 eligible**; CSV path: 2 (Sunday `STALE_REPEAT_CARRYOVER`). Regression vs the CSV audit logic |
| **06:08 IST poll (cron `38 0 * * *`) before the 09:30 publication** | `_parse_source_clock_time` (`city_parser.py:109-140`) stamps **today 09:29**, 3h21m *after* the poll; the series gains a phantom point with yesterday's price (3 → 5 for one real publication) |

**Why this is not graded critical:** the real row in your local DB has a seconds-precision source time (`04:07:32 UTC`), which shows the live page currently supplies a full timestamp (`parse_full_kjpl_datetime`). The defect fires only when the parser falls back to clock-only text, as every historical CSV row did.

**Required:**
- Reject or quarantine any MJDTA `source_published_at > observed_at`.
- For clock-only text, roll to the previous IST day when the clock is after the poll time.
- Mark clock-only rows `INFERRED` so the stale-carryover rule can apply.

### NEW-3 — target isolation → **VERIFIED FIXED**

The loader now filters `CHENNAI` + `source_product_id='MJDTA_GOLD'` + `VALID` + product purity 0.9990 / unit 1g / `MJDTA_BENCHMARK` (`mjdta_series.py` loader). The DB hindsight trigger uses the same filter.

| Contamination attempt (VALID via real persistence) | Entered series? |
|---|---|
| ALL_INDIA `MJDTA_GOLD_24K` | No |
| MUMBAI `MJDTA_GOLD_24K` | No |
| CHENNAI, `source_product_id='GOLD'` | No |
| `MJDTA_GOLD_24K_GST` | No |
| CHENNAI/MJDTA_GOLD, observation unit `10g` (₹149,950) | Yes, normalized to ₹14,995/g (correct value; observation unit not filtered: LOW) |
| CHENNAI/MJDTA_GOLD, observation `rate_type='RETAIL'` | Yes (filter uses *product* rate_type, not the observation's: LOW) |

### F-02 — prospective ledger → **PARTIALLY FIXED**

**Migration `e8b3c1d45207`:**
- Unique key now includes `model_version` (`:26-36`).
- PG triggers `trg_forecast_runs_immutable_pg` and `trg_snapshots_immutable_pg` (BEFORE UPDATE/DELETE when OLD is PROSPECTIVE).
- `trg_forecast_runs_no_hindsight_pg` (BEFORE INSERT) (`:43-97`).

| Attack (PostgreSQL) | Result |
|---|---|
| `adv_f01_f02.py` unchanged: forged old origin / backtest into writer | Rejected |
| Raw-SQL hindsight PROSPECTIVE INSERT | **Rejected by trigger** ("3 post-origin MJDTA observation(s) already exist") |
| UPDATE / DELETE PROSPECTIVE forecast | **Rejected by trigger** |
| Model-version change | New rows under `RIDGE_STD_V2_AUDIT` (fixed) |
| Snapshot idempotency (3 runs, same origin) | 1 snapshot (fixed) |
| Two concurrent writers | One inserts 8, the other 0; no error observed (not a proof of race-freedom; no advisory lock) |
| Evaluation after maturity; target fields | 8 evaluations; `forecast_runs` target fields not written back (fixed) |
| **INSERT as BACKTEST, then `UPDATE … SET generation_mode='PROSPECTIVE'`** | **ACCEPTED.** The hindsight row now sits in the PROSPECTIVE ledger (the trigger checks only `OLD.generation_mode` and INSERT) |
| **UPDATE / DELETE PROSPECTIVE `forecast_evaluations`** | **ACCEPTED** (8 rows each); outcomes can be rewritten |
| **`TRUNCATE forecast_runs CASCADE`** | **ACCEPTED** (row triggers don't fire on TRUNCATE) |

**Required:**
- Block any UPDATE that changes `generation_mode` (or all UPDATEs on `forecast_runs`).
- Add the same immutability trigger to `forecast_evaluations`.
- Add a statement-level `BEFORE TRUNCATE` trigger, or revoke TRUNCATE/UPDATE/DELETE from the application role on Neon.

### F-03 / NEW-4 / NEW-5 — labels and clusters → **VERIFIED FIXED (app level); DB immutability missing**

**Verified:**
- Rule-flip replay leaves the historical feature unchanged (1.0 → 1.0).
- Label version now carries an implementation digest (`GOLD_SENTIMENT_V2:311514` vs `:f68b0f`, `label_store.py:55-72, 261`).
- The forecast and API read only `model_name="deterministic_rules_v2"`, using the latest label as of the cutoff (`forecast_engine.py:1016-1020, 1317-1321`).
- Time-bounded cluster IDs (90 days apart → different).
- JSONL idempotent.
- Cluster IDs stable across runs.

**Residual:**
- **MEDIUM:** `news_labels` has no DB trigger. An UPDATE and DELETE on a stored label both succeeded (inside a rolled-back transaction).
- **MEDIUM:** `_classifier_implementation_digest` hashes only `evaluate_gold_impact`'s own source and bytecode. Editing a **module-level pattern list or helper** (where the rules actually live, `gold_impact.py:35-140`) does not change the version. Bytecode also differs across Python versions, so local and CI digests can diverge.
- **LOW:** for multi-member clusters, Ollama override impacts are aggregated under `model_name="deterministic_rules_v2"` (`label_store.py:383-395`).

---

## 4. All-findings status matrix (vs Audit #2)

| ID | Audit #2 | **Audit #3** | Evidence |
|---|---|---|---|
| F-01 | Partially fixed | **VERIFIED FIXED** | DB path, CHENNAI/MJDTA_GOLD filter, frontier picks up new obs (`adv_f01_f02.py`) |
| F-02 | Partially fixed | **PARTIALLY FIXED** | Triggers work for PROSPECTIVE rows; BACKTEST→PROSPECTIVE UPDATE, evaluations, TRUNCATE open |
| F-03 | Partially fixed | **VERIFIED FIXED** (app) / DB immutability open | See §3 |
| F-04 | Not fixed | **VERIFIED FIXED** | 0 VERIFIED_SOURCE, 0 first-seen in audited archive; title/ingested_at fallback removed (`archive_audit.py:46-64,144`); live first-seen monotonic (`news_client.py:830-839`), tested |
| F-05 | Not fixed | **PARTIALLY FIXED** | Every wrong-sign / wrong-bank example cited in Audit #2 is now correct ("cools/fade/pare … hike bets" → BULLISH; "Powell: cuts not on the table" → BEARISH; RBI/ECB no longer FED_POLICY; "holds as expected" → NEUTRAL). New counterexamples still wrong: "Fed cuts rates by 25 bps as widely expected" → BULLISH (AS_EXPECTED ignored, `gold_impact.py:92`); "Fed officials push back against rate cut expectations" → BULLISH; "Fed surprises markets with 50 bps cut" → UNKNOWN; "Fed holds rates, signals no cuts this year" → UNKNOWN. ECB/BoJ rate moves given direction under `CENTRAL_BANKS` (`:128-131`), conflating gold-buying and policy. Archive: dovish wrong-sign 3/10 (was 6/10); non-Fed→FED 1 |
| F-06 | Verified fixed | **VERIFIED FIXED** | MIXED 8 on archive |
| F-07 | Partially fixed | **PARTIALLY FIXED** | 441 price-move headlines unflagged, 88 directional (was 489/97). **Over-exclusion:** "Gold price today in India: RBI hikes repo rate by 25 bps" → PRICE_REPORT (`gold_impact.py:35-41`); 20 archive macro headlines absorbed. "Gold hits record high on safe-haven demand" → BULLISH GEOPOLITICS |
| F-08 | Verified fixed | **VERIFIED FIXED** | Unchanged logic; dedicated test removed (see §6) |
| F-09 | Verified fixed | **VERIFIED FIXED** | Common-origin metrics |
| F-10 | Partially fixed | **VERIFIED FIXED** | Quiet successful day → `coverage_ok=True`, `net_impact=0.0`; failed / none / stale(>24 h) / partial <50% → unavailable, `None`. Residual LOW: an older success plus a newer FAILED run in the window still counts as covered |
| F-11 | Verified fixed | **VERIFIED FIXED** | Fail-closed (Audit #2 tests, code unchanged) |
| F-12 | Verified fixed | **VERIFIED FIXED** | Import closure (tests pass without the xgboost stub path) |
| F-13 | Verified fixed | **VERIFIED FIXED** | Unchanged |
| F-14 | Partially fixed | **VERIFIED FIXED** | Independent HLN match (n=25, h=1/3); NaN/inf → `INVALID_NON_FINITE_LOSS`; constant diff → `DEGENERATE_CONSTANT_DIFFERENTIAL`; h>1 uses non-overlapping origins with `effective_h=1` (`forecast_engine.py:205-272, 563-605`) |
| F-15 | Partially fixed | **VERIFIED FIXED** (DB path) | New URL/recurring headline stored; CSV path disabled in CI |
| F-16 | Partially fixed | **VERIFIED FIXED** with LOW residuals | §3 NEW-1 residuals |
| F-17 | Partially fixed | **VERIFIED FIXED** | Blind sheet, `stratum_weight`, `sampling_weighted_accuracy`, `invalid_label_rows` reported; 0/250 → `PENDING_HUMAN_ANNOTATIONS` |
| F-18 | Partially fixed | **VERIFIED FIXED** | `latest_forecasts` = prospective only; backtests under `backtest_latest_forecasts` (`forecast_engine.py:1338-1340`); column "RAW SCORE (UNCALIBRATED)"; protocol corrected. Cosmetic: docstring still says "calibrated" (`:179`) |
| F-19 | Partially fixed | **PARTIALLY FIXED** | Migrations now run in CI, but in **two concurrency groups** (`kjpl-collector-*`, `news-collector-*`) with no Alembic lock in `migrations/env.py`. `c4d912f8a103` still conditional. Evaluations/labels lack DB immutability |
| F-20 | Partially fixed | **PARTIALLY FIXED** | Protocol declares legacy isolation, but `pipeline-update.yml` still runs legacy `update_pipeline.py` (FinBERT/Yahoo-CSV features) daily |
| F-21 | Partially fixed | **PARTIALLY FIXED** | Now wired (`collect_news_csv.py:102-121`); JSON-schema `format`, `num_predict 384`, retries, digest and prompt persisted; invalid output rejected. **Defects:** 3 identical classifications → 3 rows (no idempotency); one DB error → `PendingRollbackError` for every later cluster, swallowed by `except Exception: continue`. Live daemon **NOT VERIFIED** |
| F-22 | Partially fixed | **PARTIALLY FIXED** | Protocol now matches CHENNAI/MJDTA_GOLD, uncalibrated scores, quiet-day semantics, h=3 policy. Still overstated: "Protocol Hash / Freezing … enforced" (no protocol hash exists); "DB immutability triggers" (cover forecast_runs/snapshots only); "preserving every distinct publication" (clock-only fallback) |
| NEW-1 | Critical | **VERIFIED FIXED** | §3 |
| NEW-2 | Critical | **VERIFIED FIXED** / residual (clock-only) | §3 |
| NEW-3 | High | **VERIFIED FIXED** | §3 |
| NEW-4 | High | **VERIFIED FIXED** | 90-day test |
| NEW-5 | High | **VERIFIED FIXED** | Cross-run test |
| NEW-6 | Medium | **VERIFIED FIXED** | model_name filter |
| NEW-7 | Medium | **VERIFIED FIXED** | 1 snapshot per origin |
| NEW-8 | Medium | **VERIFIED FIXED** | Clean-DB suite passes |
| NEW-9 | Low | **VERIFIED FIXED** | `git diff --check` clean |

**Tally:** 22 verified fixed · 8 partially fixed · 0 not fixed · NOT VERIFIED: live Ollama, live Neon, `next build`.

---

## 5. Newly discovered defects (Audit #3)

| ID | Severity | Location | Finding | Reproduction |
|---|---|---|---|---|
| A3-1 | **HIGH** | `e8b3c1d45207:46-97` | BACKTEST→PROSPECTIVE `UPDATE` bypasses both triggers | `adv3_ingest_ledger.py` "UPDATE that BACKTEST row" → ACCEPTED |
| A3-2 | **HIGH** | migration (no trigger) | `forecast_evaluations` UPDATE/DELETE accepted | consistent-clock test: 8 rows updated, 8 deleted |
| A3-3 | MEDIUM | migration | `TRUNCATE forecast_runs CASCADE` accepted | `adv3_ingest_ledger.py` |
| A3-4 | MEDIUM | migration (no trigger) | `news_labels` UPDATE/DELETE accepted | psql on test DB (rolled back) |
| A3-5 | MEDIUM-HIGH (conditional) | `city_parser.py:109-140`; `persistence.py:172-176` | Clock-only time → today's date, no future guard → phantom/stale publications | `adv3_ingest_ledger.py` NEW-2(a)(b) |
| A3-6 | MEDIUM | `label_store.py:55-72` | Version digest ignores module-level rule tables; Python-version dependent | code review |
| A3-7 | MEDIUM | `ollama/classifier.py` `classify_and_persist`; `collect_news_csv.py:102-121` | No idempotency; no rollback; swallowed session poisoning | mocked-HTTP test on PG |
| A3-8 | MEDIUM | `kjpl-collector.yml:43-50`; `news-collector.yml:34-40`; `migrations/env.py` | Concurrent `alembic upgrade` possible across two concurrency groups | config review |
| A3-9 | MEDIUM | `gold_impact.py:35-41` | "Gold price today: <macro event>" swallowed as price report | classifier run |
| A3-10 | LOW | `persistence.py:411-428` | Same-time price correction appends a second publication | `adv3_ingest_ledger.py` NEW-2(c) |
| A3-11 | LOW | `mjdta_series.py` loader | Observation unit / rate_type not filtered (product-level only) | §3 NEW-3 table |
| A3-12 | LOW (process) | `tests/test_research_forecast_and_leakage.py` | 10 tests removed, 6 added. Removed tests include the F-03 sign-flip, F-08/F-09 arms, F-16 midnight and Ollama strict-JSON tests; equivalent assertions were not all carried over | test inventory diff |

---

## 6. Test execution record

| Item | Command / method | Result |
|---|---|---|
| Backend, clean DB | `cd backend && rm -f data/goldsense.db && PYTHONPATH=.:<vendored deps> python -m pytest tests/ -q --ignore=tests/test_sentiment_analyzer.py` | **119 passed** (Audit #2: 123 with a pre-populated DB). FinBERT tests (3) not run: torch unavailable |
| Test inventory | diff of `def test_` names | 126 → 122 defined; see A3-12 |
| Migrations (PG 16.15) | `alembic upgrade head` → `check` → `downgrade base` → `upgrade head` | All rc=0; "No new upgrade operations detected"; 3 triggers present |
| `adv_f01_f02.py` (unchanged) | fresh PG DB | **All checks pass** (20/20, ALL_INDIA excluded, DB rejects hindsight and UPDATE, model version separated, 16 evaluations) |
| `adv_f03.py` (unchanged) | fresh PG DB | **All checks pass** (no crash, replay safe, versioned, stable clusters, JSONL idempotent). Note: its printed text "(rule change NOT reflected…)" is hard-coded; the versions now differ |
| New attacks | `adv3_ingest_ledger.py`, `adv3_clusters.py`, inline tests | See §3 and §5 |
| Frontend | ESLint `--no-cache`; `tsc --noEmit --incremental false` (on your Mac's Linux VM, read-only) | **rc=0 / rc=0** |
| `next build` | — | **NOT VERIFIED.** Only `@next/swc-darwin-arm64` is installed and the shell is Linux aarch64; running a build would also write `.next/` into your tree. Run `npm run build` on macOS |
| Workflows | YAML parse + install-set vs import closure | Parse OK; news collector and migration imports covered |
| `git diff --check` | on device | rc=0 |

---

## 7. PostgreSQL verification status

- **Local PostgreSQL 16.15:** VERIFIED (migration lifecycle, triggers, all adversarial scripts).
- **Live Neon:** NOT VERIFIED. Not contacted, per instructions. Note: trigger-based guards depend on the app role not being able to `DROP TRIGGER`. Use a separate migration role on Neon and revoke DDL/TRUNCATE from the runtime role.

---

## 8. Workflow lifecycle

- **KJPL:** migrate (guarded) → MJDTA persist to Neon → prospective forecast (same job; sequential).
- **News:** migrate (guarded) → collect → Neon (articles, clusters, labels, run health); CSV/JSONL off.
- **Gaps:**
  - Migration races across workflows (A3-8).
  - Legacy `pipeline-update.yml` still scheduled (F-20).
  - The GitHub remote still runs the **old** auto-committing workflows until this tree is pushed (§2).

---

## 9. Remaining items before deployment preparation (bounded)

1. Close DB-level gaps A3-1 to A3-4: full-row immutability on `forecast_runs`, `forecast_evaluations`, `news_labels`; TRUNCATE guard; role privileges.
2. Clock-only timestamp guard (A3-5).
3. A single migration job, or `pg_advisory_lock` in `env.py` (A3-8).
4. Ollama: idempotency key and rollback, or keep `OLLAMA_ENABLED` off for v1 (A3-7).
5. Make the label version digest cover the rule tables (A3-6).
6. Restore the removed regression tests (A3-12).
7. Run `npm run build` on macOS.
8. Migrate the local DB to head.
9. Reconcile with `origin/develop` and disable the old remote workflows before pushing.

**Not blocking deployment preparation, but blocking any predictive claim:**
- F-05/F-07 residual classifier errors.
- 0/250 human annotations.
- 0 matured prospective origins.

---

## 10. Final readiness decision

| Question | Answer |
|---|---|
| Five-city terminal safe | YES (unchanged) |
| MJDTA target isolated | **YES** |
| MJDTA target continuity | **YES** for full-timestamp source; conditional risk on clock-only fallback |
| News pipeline durable under syndication | **YES** |
| Labels leakage-safe (app) | **YES**; DB immutability **NO** |
| Prospective ledger tamper-resistant | **PARTIAL** (A3-1 to A3-3) |
| Statistics correct | **YES** |
| Sentiment defensible for claims | **NO** (residual errors; human validation pending) |
| Live Neon / Ollama / Vercel build | **NOT VERIFIED** |
| Controlled deployment preparation | **CONDITIONAL**: close §9 items 1–4 first |

**Verdict: CONDITIONAL PASS — specific bounded issues remain.**

*Temporary audit files: `~/dhruv files/gold/_claude_audit_tmp/third/` (outside the repo; safe to delete).*
