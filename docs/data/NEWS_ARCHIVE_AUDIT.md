# VMD Bullion News Archive Audit & Provenance Remediation Report

- **Audited at (UTC):** `2026-11-11T14:15:30.751281+00:00`
- **Raw Archive Preserved:** `news_articles.csv` (3937 rows — preserved untouched)
- **Audited Output:** `news_archive_audited.csv`
- **Published Range:** `2026-09-18T10:15:00+00:00` to `2026-11-10T15:20:05+00:00`
- **Distinct Non-Fixture/Non-Duplicate Clusters (`CLUSTER_V2`):** `3620`

## Provenance Classification Breakdown

| Provenance Status | Row Count | Share (%) | Modeling / Live Eligibility |
|---|---:|---:|---|
| `VERIFIED_SOURCE` | 0 | 0.00% | Genuine collector ingest with verified `first_seen_at`; eligible for strict cutoff `T` evaluation. |
| `HISTORICAL_UNVERIFIED_AVAILABILITY` | 3913 | 99.39% | Genuine GDELT / Google News RSS record lacking `first_seen_at`; usable only for descriptive audit/human review, excluded from strict `first_seen_at <= T` availability gates. |
| `SYNTHETIC_FIXTURE` | 23 | 0.58% | Seed fixture with fabricated bare editorial `-YYYY-MM-DD` URL slug; **strictly excluded** from features, sentiment consensus, training, and human review. |
| `DUPLICATE` | 1 | 0.03% | Duplicate canonical URL or identical same-day normalized headline; excluded to prevent wire reprint inflation. |
| `INVALID` | 0 | 0.00% | Missing required title/URL/timestamp; excluded. |

## Synthetic Seed Fixtures Identified & Excluded

Detected **23** seed rows using synthetic bare editorial date URL slugs without publisher article IDs:

| Row Index | Published At | Source | URL |
|---:|---|---|---|
| 0 | `2026-09-18T10:15:00+00:00` | `reuters.com` | `https://reuters.com/markets/commodities/gold-steady-2026-09-18` |
| 1 | `2026-09-18T18:30:00+00:00` | `bloomberg.com` | `https://bloomberg.com/news/fed-rate-outlook-gold-2026-09-18` |
| 2 | `2026-09-19T02:45:00+00:00` | `economictimes.com` | `https://economictimes.indiatimes.com/markets/gold-demand-india-2026-09-19` |
| 3 | `2026-09-19T03:40:00+00:00` | `cnbc.com` | `https://cnbc.com/markets/currencies/us-dollar-firms-2026-09-19` |
| 4 | `2026-09-20T03:10:00+00:00` | `reuters.com` | `https://reuters.com/markets/commodities/metals-retreat-2026-09-20` |
| 5 | `2026-09-21T02:30:00+00:00` | `bloomberg.com` | `https://bloomberg.com/markets/gold-slips-asian-trade-2026-09-21` |
| 6 | `2026-09-21T03:35:00+00:00` | `livemint.com` | `https://livemint.com/market/commodities/kjpl-bullion-cautious-buying-2026-09-21` |
| 7 | `2026-09-22T03:00:00+00:00` | `ft.com` | `https://ft.com/content/central-banks-gold-accumulation-2026-09-22` |
| 8 | `2026-09-22T03:50:00+00:00` | `wsj.com` | `https://wsj.com/finance/commodities/gold-drops-dollar-weighs-2026-09-22` |
| 9 | `2026-09-23T03:20:00+00:00` | `reuters.com` | `https://reuters.com/markets/commodities/bullion-extends-decline-2026-09-23` |
| 10 | `2026-09-23T14:15:00+00:00` | `cnbc.com` | `https://cnbc.com/markets/stocks/tech-rally-wall-street-2026-09-23` |
| 11 | `2026-09-24T03:15:00+00:00` | `bloomberg.com` | `https://bloomberg.com/markets/gold-falls-two-week-low-2026-09-24` |
| 12 | `2026-09-24T22:00:00+00:00` | `reuters.com` | `https://reuters.com/markets/commodities/bargain-hunting-gold-2026-09-24` |
| 13 | `2026-09-25T03:25:00+00:00` | `economictimes.com` | `https://economictimes.indiatimes.com/markets/gold-rebounds-india-2026-09-25` |
| 14 | `2026-09-25T16:00:00+00:00` | `wsj.com` | `https://wsj.com/finance/commodities/oil-prices-drop-inventory-2026-09-25` |
| 15 | `2026-09-26T02:50:00+00:00` | `reuters.com` | `https://reuters.com/markets/commodities/gold-consolidates-support-2026-09-26` |
| 16 | `2026-09-27T18:00:00+00:00` | `bloomberg.com` | `https://bloomberg.com/markets/dollar-strengthens-peak-2026-09-27` |
| 17 | `2026-09-28T03:10:00+00:00` | `reuters.com` | `https://reuters.com/markets/commodities/sharp-sell-off-gold-2026-09-28` |
| 18 | `2026-09-28T03:45:00+00:00` | `economictimes.com` | `https://economictimes.indiatimes.com/markets/gold-tumbles-india-2026-09-28` |
| 19 | `2026-09-28T07:30:00+00:00` | `ft.com` | `https://ft.com/content/european-gold-selling-pressure-2026-09-28` |
| 20 | `2026-09-28T10:15:00+00:00` | `livemint.com` | `https://livemint.com/market/commodities/afternoon-bullion-check-slide-2026-09-28` |
| 21 | `2026-09-28T18:00:00+00:00` | `bloomberg.com` | `https://bloomberg.com/markets/precious-metals-worst-day-2026-09-28` |
| 22 | `2026-09-29T03:20:00+00:00` | `economictimes.com` | `https://economictimes.indiatimes.com/markets/gold-steadies-india-2026-09-29` |

## Normalized Languages (Top 12)

| Language Code | Article Count |
|---|---:|
| `en` | 2429 |
| `zh` | 726 |
| `es` | 76 |
| `fr` | 75 |
| `ar` | 67 |
| `tr` | 63 |
| `vi` | 61 |
| `ru` | 48 |
| `hi` | 44 |
| `bn` | 40 |
| `de` | 33 |
| `it` | 32 |

## Integrity Guarantees

1. Legacy `data/news/news_articles.csv` is **preserved intact** (zero rows deleted).
2. `first_seen_at` is **never backfilled or reconstructed from `published_at`**.
3. Only articles with genuine collector capture timestamps receive `VERIFIED_SOURCE`; legacy unverified rows are tagged `HISTORICAL_UNVERIFIED_AVAILABILITY`.
