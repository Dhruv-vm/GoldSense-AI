# Incident Report: Five-City Gold Rate Sub-₹1,000 Contamination & Unit Defect

- **Incident Date Identified:** 2026-11-11
- **Status:** Resolved in Codebase & Local SQLite (`develop`); Live GitHub Actions / Neon Cutover Pending Push & Secret Provisioning
- **Affected Subsystem:** KJPL Pipeline (`scripts/collect_kjpl_csv.py`, `backend/app/services/kjpl/city_parser.py`, `persistence.py`, `bullion_service.py`, Alembic `a7c3e91b42d0`, `frontend/app/page.tsx`)

---

## 1. Symptom Reported
Only **one** city gold rate (Chennai via MJDTA Gold 24K, ~₹13,015–₹13,210/g) displayed a valid gold rate while the remaining **four** city rates (**Bengaluru, Mumbai, Coimbatore, Hyderabad**) displayed values **below ₹1,000/g** (e.g., `₹1.00/g`, `₹0.51/g`, `₹0.52/g`, or raw stored `₹100.00` / `₹51.00` / `₹52.00`).

---

## 2. Verified Root Cause & Exact Pipeline Evidence

Inspection of the active `origin/develop` (`HEAD = 06fdf0a`) workflow log (**GitHub Actions Run ID `42986186175`** at `2026-11-11T08:20:25Z`), `data/kjpl/quarantined_city_rates.csv`, and live KJPL endpoints established a multi-stage defect:

1. **GitHub Actions HTML `#liveratetable` Placeholder Scraping:**
   - KJPL's initial HTML (`http://www.kjpl.in/`) renders `-` in the live sell-rate cells of `#liveratetable` (`tr.ratelive` for `com_id` `47`–`52`) until `booking.js` hydrates prices asynchronously from `ws://www.kjpl.in/ws` and `http://www.kjpl.in/client/kjpl.txt`.
   - `HEAD:backend/app/services/kjpl/city_parser.py` fell back to a generic `soup.find_all("tr")` scan picking `valid_numbers = [n for n in numbers if n > 50.0][-1]` across concatenated DOM cells:
     - **Chennai (`com_id=48`)** — extracted `100.00` (`com_display_purity`) on `GOLD_100G_999`, while Chennai's separate MJDTA table row (`MJDTA_GOLD_24K`) yielded valid `13,015.00` / `13,210.00` INR/g.
     - **Bengaluru (`com_id=49`)** — extracted `100.00` (`com_display_purity`).
     - **Mumbai (`com_id=50`)** — extracted `100.00` (`com_display_purity`).
     - **Coimbatore (`com_id=51`)** — extracted `51.00` (`com_id = 51 > 50.0`).
     - **Hyderabad (`com_id=52`)** — extracted `52.00` (`com_id = 52 > 50.0`).
   - Run ID `42986186175` output on `origin/develop`:
     - `CHENNAI | MJDTA_GOLD_24K | ₹13,015.00 (1g)`
     - `BENGALURU | GOLD_100G_999 | ₹100.00 (100g)`
     - `MUMBAI | GOLD_100G_999 | ₹100.00 (100g)`
     - `COIMBATORE | GOLD_100G_999 | ₹51.00 (100g)`
     - `HYDERABAD | GOLD_100G_999 | ₹52.00 (100g)`

2. **Weight/Unit Misdivision (`weight=100.0`, `unit="100g"`):**
   - `HEAD:persistence.py` (`DEFAULT_PRODUCTS`) and `HEAD:city_parser.py` assumed `GOLD_100G_999` (`48..52`) were quoted per `100g` (`weight = 100.0`), so `HEAD:bullion_service.py` divided `latest_price / 100.0`:
     - `100.00 / 100.0 = ₹1.00/g` (Bengaluru, Mumbai, Chennai `100g` bar)
     - `51.00 / 100.0 = ₹0.51/g` (Coimbatore)
     - `52.00 / 100.0 = ₹0.52/g` (Hyderabad)
   - Live verification of KJPL `get_rpanel_data` (`com_weight = "1.000"`), `http://www.kjpl.in/client/kjpl.txt`, and `ws://www.kjpl.in/ws` confirmed KJPL actually quotes **all six live Type 3 products (`47`–`52`) directly in INR per 1 gram** (`~₹14,465.00–₹14,482.00/g` on `2026-11-11`).

3. **Additional Secondary Defects Found During Investigation:**
   - Scheduled `scripts/collect_kjpl_csv.py` needed a single snapshot fetch of `kjpl.txt` + `get_rpanel_data` alongside HTML MJDTA extraction (plus structured `[COLLECTOR_ITEM]` logs) so scheduled runs populate all 5 cities independently.
   - `seed_bullion_metadata()` previously skipped updating existing `BullionProduct` metadata if rows already existed (`weight=100.0, unit='100g'`).
   - Migration `a7c3e91b42d0` needed an automatic SQL backfill to quarantine pre-existing `< ₹5,000` INR gold / `< ₹80` INR silver rows if upgrading an already-populated DB.
   - `persistence.py` previously persisted timezone-aware IST `source_published_at` without normalizing to `.astimezone(timezone.utc)` first, causing SQLite to strip the offset and `_format_pub_time_ist` to shift `+05:30` twice (`02:30 PM` -> `08:00 PM IST`).

---

## 3. Before vs. After Diagnostic Table (Verified `2026-11-11`)

| City | KJPL Product ID | Legacy `origin/develop` Raw / Displayed | Live KJPL Source (`kjpl.txt` / `ws`) | Raw Unit | Stored DB Value | API `per_gram_price` | API `validation_status` / Freshness |
|---|---:|---:|---:|---|---:|---:|---|
| Chennai | `48` | `100.0` (`₹1.00/g`, beside MJDTA `₹13,015`) | `14465.00` | `1g` | `14465.00` | `14465.0` | `VALID` / `LIVE` |
| Bengaluru | `49` | `100.0` (`₹1.00/g`) | `14465.00` | `1g` | `14465.00` | `14465.0` | `VALID` / `LIVE` |
| Mumbai | `50` | `100.0` (`₹1.00/g`) | `14465.00` | `1g` | `14465.00` | `14465.0` | `VALID` / `LIVE` |
| Coimbatore | `51` | `51.0` (`₹0.51/g`) | `14465.00` | `1g` | `14465.00` | `14465.0` | `VALID` / `LIVE` |
| Hyderabad | `52` | `52.0` (`₹0.52/g`) | `14465.00` | `1g` | `14465.00` | `14465.0` | `VALID` / `LIVE` |

*(Verified `2026-11-11T09:26:03Z` / `14:56:03 IST` collector run `1c52c60cd002` against `http://www.kjpl.in/`, `http://www.kjpl.in/client/kjpl.txt`, `http://www.kjpl.in/index.php/C_booking/get_rpanel_data`, and `ws://www.kjpl.in/ws`.)*

---

## 4. Files Modified & Remediation Summary
- `backend/app/services/kjpl/city_parser.py` — Removed brute-force `<tr>` fallback; added strict `parse_kjpl_live_feed()` for `ws` & `kjpl.txt` Type 1/2/3/4 feeds with `com_id` `47..52` per-1g unit detection.
- `backend/app/services/kjpl/validator.py` — Enforced `5000.0 <= per_gram <= 50000.0` for gold and rejection of `100.0` weight / `com_id` artifacts.
- `backend/app/services/kjpl/persistence.py` — Repaired existing `BullionProduct` metadata in `seed_bullion_metadata()`, normalized `source_published_at` to UTC internally, and emitted per-item persistence logs.
- `backend/migrations/versions/a7c3e91b42d0_add_numeric_precision_and_quarantine_fields.py` — Added `Numeric` precision, quarantine schema, product metadata fix, and pre-migration SQL quarantine backfill for `< 5000` gold / `< 80` silver.
- `scripts/collect_kjpl_csv.py` — Collects Pipeline A MJDTA HTML + single scheduled `kjpl.txt`/`get_rpanel_data` snapshot with structured `[COLLECTOR_ITEM]` logs (`collector_run_id`, `source_product_id`, `city`, `raw_value`, `raw_unit`, `normalized_value`, `normalized_unit`, `validation_status`, `persistence_result`).
- `backend/app/services/bullion_service.py` & `frontend/app/page.tsx` — Added `source_product_id`, `purity`, `unit`, and `validation_status` across city matrix tables, fixed Card 3 wholesale `1g` / `1KG` framing, and removed `null` spread formatting artifacts.
- `backend/tests/test_kjpl_city_extraction.py` & `backend/tests/test_bullion_api.py` — Added regression tests covering all 5 IDs (`48..52`) + `47`, sub-`₹1,000` rejection across every city, legacy metadata repair, collector execution, market closure, production no-CSV fallback, and UTC->IST formatting.
