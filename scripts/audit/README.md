# Adversarial audit scripts

These scripts attack the real persistence, forecasting and labelling code paths, using **synthetic fixtures**. They are referenced by the reports in [`docs/audits/`](../../docs/audits/README.md).

> **Only run against a disposable local PostgreSQL database.**
> The scripts insert synthetic MJDTA observations, news, labels and forecasts, and try to tamper with tables. **Never point `DATABASE_URL` at Neon or any shared database.**

| Script | Audit | What it tests |
|---|---|---|
| `adv_f01_f02.py` | 2 (rerun in 3) | MJDTA continuity, ALL_INDIA contamination, prospective ledger guards, model-version identity, maturation |
| `adv_f03.py` | 2 (rerun in 3) | Label replay after a rule flip, version lineage, idempotency, cluster stability, two-member clusters, JSONL |
| `adv3_ingest_ledger.py` | 3 | Clock-only timestamp replay, phantom publications, poll dedup, quarantine, contamination attempts, BACKTEST→PROSPECTIVE bypass, TRUNCATE, concurrency |
| `adv3_clusters.py` | 3 | Overlapping batches, late arrivals, URL changes, cross-day bulletins, near-duplicate story merges |
| `adv_f03_v2.py` | Final verification | Updated variant of `adv_f03.py` (changes marked `[V2]`): true identical-rerun idempotency check, computed version check, and the two-member attack on both a different-event pair (must split) and a same-story pair (must merge) |
| `adv3_ingest_ledger_v2.py` | Final verification | Updated variant of `adv3_ingest_ledger.py` (changes marked `[V2]`): extra synthetic history and a pinned forecast time so the F-02 ledger attacks run against real PROSPECTIVE evaluations. Same attack set |
| `app_challenge.py` | Final verification | Application-level probes: clock-only rollback and skew, future quarantine, carry-over false positive, same-publication correction after forecasting, concurrent Ollama writes, digest stability, protocol hash. Uses its own throwaway SQLite DB (no PostgreSQL needed) |

## Running

```bash
# 1. Start a throwaway PostgreSQL 16 and create an empty database, e.g. vmd_audit
createdb vmd_audit

# 2. Migrate it and run a script from backend/
cd backend
export DATABASE_URL="postgresql://postgres@localhost:5432/vmd_audit"
export REQUIRE_POSTGRES=true TZ=UTC
alembic upgrade head
PYTHONPATH=. python ../scripts/audit/adv_f01_f02.py

# 3. Use a fresh database for each script (they leave data behind), then drop it
dropdb vmd_audit
```

`adv_f03.py` writes a temporary JSONL file to the system temp directory only.

### Original vs `_v2` scripts

The originals are kept unchanged as the record of what Audits #2 and #3 ran. After the Audit #3 remediation, some of their expected output is outdated:

- `adv3_ingest_ledger.py` stops at `series(db)[0][5]`, because the Sunday carry-over no longer inflates the series.
- `adv_f03.py`'s "identical rerun" follows its own rule-flip revert, so appending there is correct.

Use the `_v2` variants for current results. Run them exactly like the originals (fresh database each time).

`app_challenge.py` must be run from `backend/` because it imports test helpers:

```bash
cd backend
PYTHONPATH=. TZ=UTC python ../scripts/audit/app_challenge.py
```

Several of its lines are expected to show **open defects** (carry-over false positive, clock-skew dating, duplicate forecasts after a correction, concurrent Ollama duplicate). See the final verification notes.
