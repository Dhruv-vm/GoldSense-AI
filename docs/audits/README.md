# Independent Forensic Audits (Claude)

Independent reviews of the VMD Bullion research and engineering upgrade, run against the local `develop` working tree.

| # | Report | Verdict | Scope |
|---|---|---|---|
| 1 | [CLAUDE_AUDIT_1_2026-11-11.md](CLAUDE_AUDIT_1_2026-11-11.md) | FAIL — critical defects found | Original implementation; findings F-01 to F-22 |
| 2 | [CLAUDE_AUDIT_2_2026-11-11.md](CLAUDE_AUDIT_2_2026-11-11.md) | FAIL — critical defects remain | First remediation; adds NEW-1 to NEW-9 |
| 3 | [CLAUDE_AUDIT_3_2026-11-11.md](CLAUDE_AUDIT_3_2026-11-11.md) | **CONDITIONAL PASS** | Second remediation; adds A3-1 to A3-12 |

The adversarial test scripts used in audits 2 and 3 are in [`scripts/audit/`](../../scripts/audit/README.md).

## Open items from Audit 3 (close before deployment preparation)

1. **A3-1 to A3-4 — database immutability gaps.**
   - A BACKTEST row can be UPDATEd to PROSPECTIVE.
   - `forecast_evaluations` and `news_labels` can be UPDATEd or DELETEd.
   - `TRUNCATE` is not blocked.
2. **A3-5 — clock-only KJPL timestamp fallback.** It can stamp a future publication time and create phantom MJDTA observations.
3. **A3-8 — concurrent `alembic upgrade`** can run across the KJPL and news workflows.
4. **A3-7 — Ollama label writer** is not idempotent and has no rollback. Keep `OLLAMA_ENABLED` off until fixed.
5. **A3-6 / A3-12 — label version digest scope; restore the removed regression tests.**
6. **Not verified yet:** `next build` (run on macOS), live Neon, live Ollama.
