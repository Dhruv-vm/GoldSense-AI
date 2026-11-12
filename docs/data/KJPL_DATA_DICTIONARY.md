# KJPL VERIFIED DATA DICTIONARY & DUAL-PIPELINE CONTRACT (PHASE 1)

> **Verification Date:** 2026-11-11 (Live inspection of `http://www.kjpl.in/`)  
> **Upstream Provider:** Kerala Jewellers / KJPL (`http://www.kjpl.in/`) — Exclusive bullion and market rate source  
> **Scope:** Authoritative field semantics, units, update frequencies, and internal data contracts for Pipeline A (MJDTA Reference) and Pipeline B (KJPL Live Terminal).

---

## 1. Upstream Mechanisms Verified from Live Source

| Mechanism | URL / Transport | Auth / Headers | Observed Cadence | Contents |
|---|---|---|---|---|
| **Static HTML Page** | `GET http://www.kjpl.in/` | Standard `User-Agent` | Twice daily (MJDTA ~09:35–10:30 AM & afternoon updates); LBMA daily | MJDTA Gold/Silver (With & Without GST + full `UPDATED:` timestamp), LBMA AM/PM London Fixes, initial DOM shell for `#liveratetable` (`-` until JS hydrates), inline bootstrap JS config. |
| **RPanel Metadata API** | `GET http://www.kjpl.in/index.php/C_booking/get_rpanel_data` | Standard `User-Agent` | On page load / `kjplupdaterpanel` event | JSON object containing `commoditydetails` (IDs `47`–`52`), `rpaneldata` (`market_status`, `lastupdatetime`), `rpanelsettings`, `rpanelbank` (import costing inputs), `rpanel_contracts`, `rpanel_commodities`. |
| **Live WebSocket (`bcrate_Type == 5`)** | `ws://www.kjpl.in/ws` | Subprotocol `[SOCKET_TOKEN]` (publicly embedded in page HTML) | **Continuous (~1–2s tick stream during active market hours)**; heartbeat `ping`/`pong` | Pipe-delimited real-time frames (`1\|G`, `1\|S`, `1\|I`, `2\|GOLD`, `2\|SILVER`, `3\|47..52`, `4\|4\|<rate_display>\|<market_status>\|<msg>`). |
| **Live Snapshot Text Feed** | `GET http://www.kjpl.in/client/kjpl.txt` | Standard `User-Agent` | **Updated ~every 1 second** (verified `14:06:17` -> `14:06:21` PM) | Tab-delimited snapshot mirror of live feed PLUS full Type 4 server timestamp string `"MM/DD/YYYY hh:mm:ss AM/PM"`. |
| **Forbidden / Unused Endpoints** | `/index.php/C_rates/rate_data` (403), `/lmxtrade/winbullliteapi/api/v1/broadcastrates` (405) | N/A | N/A | Present in legacy JS variables; not used by `bcrate_Type == 5`. |

> **Network Accessibility Note:** Cloud/local runners may periodically face WAF/IP 403 filtering on `http://www.kjpl.in/`. Both collectors handle HTTP 403/timeouts gracefully, log `SOURCE_UNAVAILABLE`, and preserve last verified rates without fabrication.

---

## 2. Pipeline A — MJDTA Reference Collector (GitHub Actions Scheduled)

- **Source Target:** `GET http://www.kjpl.in/` (specifically `.chennairate_table` tables for MJDTA & fallback `.gold-rate` / `.silver-rate` / `.mjdma_data`).
- **Expected Update Frequency:** ~2 times/day on trading days (morning opening ~09:30–10:30 AM IST; occasional afternoon revision). Closed Sundays.

### Verified Field Semantics (HTML Tables 10, 11, 14, 15)

| Source Selector / Row | Field Meaning | Verified Currency & Unit | Purity | Derived Product ID |
|---|---|---|---|---|
| `.chennairate_table` (`MJDTA RATE (Without GST)`) -> `GOLD:` & `.gold-rate` | MJDTA 24K Gold Reference Rate (Excl. GST) | **INR per 1 gram** | `0.999` (24K) | `MJDTA_GOLD_24K` (`CHENNAI`) |
| `.chennairate_table` (`MJDTA RATE (Without GST)`) -> `SILVER:` & `.silver-rate` | MJDTA Silver Reference Rate (Excl. GST) | **INR per 1 gram** | `0.999` | `MJDTA_SILVER` (`CHENNAI`) |
| `.chennairate_table` (`MJDTA RATE (With GST)`) -> `GOLD:` | MJDTA 24K Gold Reference Rate (Incl. 3% GST) | **INR per 1 gram** | `0.999` | `MJDTA_GOLD_24K_GST` (`CHENNAI`) |
| `.chennairate_table` (`MJDTA RATE (With GST)`) -> `SILVER:` | MJDTA Silver Reference Rate (Incl. 3% GST) | **INR per 1 gram** | `0.999` | `MJDTA_SILVER_GST` (`CHENNAI`) |
| `.chennairate_table` -> `UPDATED:` row | Full Source Publication Timestamp (e.g. `11-11-2026 09:37:32 am` IST) | Full Date+Time (`Asia/Kolkata` -> stored UTC) | N/A | `source_published_at` |

### Explicitly Excluded Cross-Contamination Tables
- **Table 0 (`.mjdmahead`)**: Single row `['GOLD 13015', 'SILVER 200']` — never parse last number across cells without checking metal label!
- **Table 9 / 13 (`TODAY'S RATE - LBMA LONDON`)**: `GOLD AM Fix: ($) 4073.70`, `GOLD PM Fix: ($) 4050.90`, `SILVER Fix: ($) 52.2850` — these are **LBMA USD per troy oz**, tracked strictly under `LBMA_GOLD_AM_USD`, `LBMA_GOLD_PM_USD`, `LBMA_SILVER_USD` (`USD/oz`), **never** as INR/gram MJDTA rates.

---

## 3. Pipeline B — KJPL Live Terminal Collector (Dedicated Oracle Cloud Worker)

- **Primary Transport:** `ws://www.kjpl.in/ws` (real-time push) backed by `http://www.kjpl.in/client/kjpl.txt` snapshot polling + `http://www.kjpl.in/index.php/C_booking/get_rpanel_data` metadata refresh.
- **Measured Update Frequency:** Continuous sub-2-second ticks during market hours (`rate_display=1`, `market_status=0`).

### A. Type 3 Rows — Physical Bullion & Five Cities (`3|<com_id>|<buy>|<sell>`)

Verified mathematically against `get_rpanel_data` (`GOLDDEC_ask = 141,695` ₹/10g + `sell_diff = 3,350` ₹/10g = `145,045 / 10` = `14,504.50` ₹/1g, plus `com_sel_premium = 17.00` for ID 47 = `14,521.50` ₹/1g):

| `com_id` | Source `com_name` | Canonical City (`city_code`) | Product ID | Purity | `com_weight` | Verified Source Quote Unit | `normalized_price_per_gram` |
|---|---|---|---|---|---|---|---|
| `47` | `GOLD 1KG 99.99` | `ALL_INDIA` (National) | `GOLD_1KG_9999` | `0.9999` | `1.000` | **INR per 1 gram** (e.g., `14521.50`) | `original_price` (1:1 INR/g; 1KG bar equiv = `original_price * 1000`) |
| `48` | `GOLD 100 GMS 999 Chennai` | `CHENNAI` | `GOLD_100G_999` | `0.999` | `1.000` | **INR per 1 gram** (e.g., `14504.50`) | `original_price` (1:1 INR/g; 100g bar equiv = `original_price * 100`) |
| `49` | `Gold 100 GMS 999 Bangalore` | `BENGALURU` | `GOLD_100G_999` | `0.999` | `1.000` | **INR per 1 gram** | `original_price` (1:1 INR/g) |
| `50` | `Gold 100 GMS 999 Mumbai` | `MUMBAI` | `GOLD_100G_999` | `0.999` | `1.000` | **INR per 1 gram** | `original_price` (1:1 INR/g) |
| `51` | `Gold 100 GMS 999 Coimbatore` | `COIMBATORE` | `GOLD_100G_999` | `0.999` | `1.000` | **INR per 1 gram** | `original_price` (1:1 INR/g) |
| `52` | `GOLD 100 GMS 999 Hyderabad` | `HYDERABAD` | `GOLD_100G_999` | `0.999` | `1.000` | **INR per 1 gram** | `original_price` (1:1 INR/g) |

> **CRITICAL FINDING:** Despite product labels mentioning `1KG` and `100 GMS`, KJPL's live WebSocket/`kjpl.txt` engine sets `com_weight = 1.000` and publishes all six rates (`47`–`52`) on a **per-1-gram INR basis** (`~14,500`). Any code dividing `14504.50` by `100.0` would produce a 100× error (`₹145.05/g`). Legacy fixture rows (`1308500.00` = 100g total, `13085000.00` = 1kg total) came from synthetic fixture HTML (`kjpl_live_sample.html`) rather than KJPL's live Type 3 feed.

### B. Type 1 & Type 2 Rows — KJPL International & MCX Benchmarks

| Type | Symbol (`ws` / `kjpl.txt`) | Meaning | Fields | Unit / Currency | Internal Product ID |
|---|---|---|---|---|---|
| `1` | `G` / `SPOT-GOLD` | KJPL Spot Gold ($) | `bid`, `ask`, `high`, `low` | **USD per troy oz** (e.g. `4059.93`) | `KJPL_SPOT_GOLD_USD` |
| `1` | `S` / `SPOT-SILVER` | KJPL Spot Silver ($) | `bid`, `ask`, `high`, `low` | **USD per troy oz** (e.g. `53.01`) | `KJPL_SPOT_SILVER_USD` |
| `1` | `I` / `SPOT-INR` | KJPL Spot USD/INR | `bid`, `ask`, `high`, `low` | **INR per 1 USD** (e.g. `93.70`) | `KJPL_SPOT_USDINR` |
| `2` | `GOLD` / `GOLDDEC` | KJPL Gold Benchmark Contract | `bid`, `ask`, `high`, `low` | **INR per 10 grams** (e.g. `141695`) | `KJPL_GOLDDEC_INR_10G` |
| `2` | `SILVER` / `SILVERDEC` | KJPL Silver Benchmark Contract | `bid`, `ask`, `high`, `low` | **INR per 1 kg** (e.g. `187300`) | `KJPL_SILVERDEC_INR_1KG` |
| `4` | `4` | Live Terminal Control & Timestamp | `rate_display` (`1`/`0`), `market_status` (`0`=open,`1`=closed), `timestamp` (`kjpl.txt`) | Control flags + IST clock | System Status |

### C. `rpanelbank` & `rpanel_commodities` Metadata (Verified Unaltered Raw Fields)

- `rpanelbank`: `bcontract_symbol` (`Gold`, `Silver`), `bcontract_rate` (`SPOT-GOLD`, `SPOT-SILVER`), `bconvert_value` (`32.1200`, `32.1508`), `btax_value` (`3.000`), `premium`, `rupeepremium`, `custom` (`858833.000` Gold, `16142.000` Silver). Preserved as raw KJPL costing reference without fabricating derived parity assumptions.
- `rpanel_commodities`: `Gold-1` (`mcxcontract=GOLDDEC`, `selldiff=3350.00`, `buydiff=0.00`, `sellrate=145223.00`), `Silver-1` (`mcxcontract=SILVERDEC`, `selldiff=5400.00`, `buydiff=0.00`, `sellrate=192981.00`). Note: `Silver-1` exists in `rpanel_commodities` but is NOT currently listed in `#liveratetable` `commoditydetails` (`len=6` for IDs `47..52`).

---

## 4. Unresolved / Flagged Semantics

1. **Live Snapshot Verification (`2026-11-11`):** Both `http://www.kjpl.in/client/kjpl.txt` and `ws://www.kjpl.in/ws` (verified live frames: `3|47|-|14483.80`, `3|48..52|-|14466.80`, `1|G|...`, `1|S|...`, `1|I|...`, `2|GOLD|...`, `2|SILVER|...`, `4|4|1|0|`) transmit Type 3 physical rates (`47..52`) on a per-1-gram INR basis matching `com_weight = 1.000`.
2. **`com_display_purity`** (`0.00` on ID 47, `100.00` on IDs 48–52): Internal display/template flag in KJPL admin UI; never parsed as price or purity.
2. **Type 3 Buying Rate (`-`)**: Currently KJPL transmits `-` for `buying_rate` (`com_buy_active = 0`). Stored as `None` (never replaced with `0`).
3. **Green / Red UI Highlights**: Verified from `booking.js` lines 507–528 & 1110–1133: `#008000` (green) = tick increased vs previous DOM cell value; `#FF0000` (red) = tick decreased vs previous DOM cell value. They represent tick direction, **not** buy/sell or bid/ask polarity.
4. **Identical City Quotes Across IDs 48–52**: Live snapshot shows identical `14504.50` across Chennai, Bengaluru, Mumbai, Coimbatore, and Hyderabad because all five currently have `com_sel_premium = 0.00` and `mcxsymbol = 1`. Each city ID (`48`–`52`) must still be parsed and persisted independently so city-level premiums/spreads are captured the moment KJPL differentiates them.

---

## 5. Product-Specific Validation Rules (Enforced in Phase 2+)

| Product ID | Metal | Currency | Source Unit | Weight Basis (g) | Valid Price Bounds (Original Unit) | Valid Normalized INR/g Bounds |
|---|---|---|---|---|---|---|
| `MJDTA_GOLD_24K` | `GOLD` | `INR` | `1g` | `1.0` | `5,000 <= p <= 50,000` | `5,000 <= p <= 50,000` |
| `MJDTA_GOLD_24K_GST` | `GOLD` | `INR` | `1g` | `1.0` | `5,000 <= p <= 52,000` | `5,000 <= p <= 52,000` |
| `MJDTA_SILVER` | `SILVER` | `INR` | `1g` | `1.0` | `80 <= p <= 1,500` *(strictly rejects USD/oz ~50–60!)* | `80 <= p <= 1,500` |
| `MJDTA_SILVER_GST` | `SILVER` | `INR` | `1g` | `1.0` | `80 <= p <= 1,600` | `80 <= p <= 1,600` |
| `GOLD_1KG_9999` (Live ID 47) | `GOLD` | `INR` | `1g` *(when `< 100,000`)* | `1.0` | `5,000 <= p <= 50,000` | `5,000 <= p <= 50,000` |
| `GOLD_100G_999` (Live IDs 48–52) | `GOLD` | `INR` | `1g` *(when `< 100,000`)* | `1.0` | `5,000 <= p <= 50,000` | `5,000 <= p <= 50,000` |
| `KJPL_SPOT_GOLD_USD` | `GOLD` | `USD` | `oz` | `31.1034768` | `1,000 <= p <= 10,000` | N/A (USD quote) |
| `KJPL_SPOT_SILVER_USD` | `SILVER` | `USD` | `oz` | `31.1034768` | `15 <= p <= 200` | N/A (USD quote) |
| `KJPL_SPOT_USDINR` | `FX` | `INR` | `USD` | `1.0` | `60 <= p <= 150` | N/A (FX quote) |
| `KJPL_GOLDDEC_INR_10G` | `GOLD` | `INR` | `10g` | `10.0` | `50,000 <= p <= 500,000` | `5,000 <= p/10 <= 50,000` |
| `KJPL_SILVERDEC_INR_1KG` | `SILVER` | `INR` | `1kg` | `1000.0` | `80,000 <= p <= 1,500,000` | `80 <= p/1000 <= 1,500` |
