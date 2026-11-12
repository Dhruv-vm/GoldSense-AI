from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    COLLECTOR_VERSION,
    ProvenanceStatus,
    QUERY_VERSION,
    assign_story_clusters,
    compute_canonical_url,
    compute_content_fingerprint,
    compute_story_cluster_id,
    is_synthetic_fixture_url,
    normalize_headline,
    normalize_language,
    parse_utc_iso,
)


AUDITED_COLUMNS = [
    "published_at",
    "first_seen_at",
    "title",
    "url",
    "canonical_url",
    "source",
    "language_raw",
    "language",
    "content_fingerprint",
    "story_cluster_id",
    "cluster_key",
    "cluster_version",
    "provenance_status",
    "exclusion_reason",
    "query_id",
    "query_version",
    "collector_version",
]


def _load_live_ingest_index(live_csv_path: Path) -> dict[str, str]:
    """Map canonical_url -> genuine `first_seen_at` (never title-only or legacy overwritten `ingested_at`)."""
    by_url: dict[str, str] = {}
    if not live_csv_path.exists():
        return by_url
    with live_csv_path.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # F-04: Only trust an explicit monotonic `first_seen_at` column; legacy `ingested_at`
            # was overwritten on re-sightings and is an upper bound rather than true first-seen.
            first_seen_raw = (row.get("first_seen_at") or "").strip()
            first_seen_dt = parse_utc_iso(first_seen_raw)
            if first_seen_dt is None:
                continue
            c_url = compute_canonical_url(row.get("url") or "")
            if c_url:
                existing_dt = parse_utc_iso(by_url[c_url]) if c_url in by_url else None
                if existing_dt is None or first_seen_dt < existing_dt:
                    by_url[c_url] = first_seen_dt.isoformat()
    return by_url


def audit_news_archive(
    raw_archive_path: Path,
    live_csv_path: Path,
    output_audited_path: Path,
    report_md_path: Path | None = None,
) -> dict[str, Any]:
    """
    Audit raw legacy news_articles.csv without modifying or deleting source rows.

    Writes an enriched provenance-tagged CSV (`news_archive_audited.csv`) and an
    optional Markdown audit report with exact observed counts.
    """
    if not raw_archive_path.exists():
        raise FileNotFoundError(f"Raw news archive not found: {raw_archive_path}")

    live_by_url = _load_live_ingest_index(live_csv_path)

    seen_urls: set[str] = set()
    seen_title_days: set[tuple[str, str]] = set()
    audited_rows: list[dict[str, Any]] = []

    status_counts: Counter[str] = Counter()
    lang_counts: Counter[str] = Counter()
    exclusion_counts: Counter[str] = Counter()
    synthetic_rows_sample: list[dict[str, str]] = []
    cluster_ids_eligible: set[str] = set()
    verified_dates: list[datetime] = []
    historical_dates: list[datetime] = []

    with raw_archive_path.open("r", encoding="utf-8") as fh:
        raw_rows = list(csv.DictReader(fh))

    for idx, row in enumerate(raw_rows):
        pub_raw = (row.get("published_at") or "").strip()
        first_seen_raw = (row.get("first_seen_at") or "").strip()
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        source = (row.get("source") or "").strip()
        lang_raw = (row.get("language") or "").strip()

        pub_dt = parse_utc_iso(pub_raw)
        first_seen_dt = parse_utc_iso(first_seen_raw)
        canonical_url = compute_canonical_url(url)
        norm_title = normalize_headline(title)
        lang_norm = normalize_language(lang_raw)
        fingerprint = compute_content_fingerprint(title, canonical_url)

        pub_day = pub_dt.date().isoformat() if pub_dt else ""
        story_cluster_id, cluster_key = compute_story_cluster_id(title, pub_dt, CLUSTER_VERSION)

        exclusion_reason = ""
        if not title or not url or pub_dt is None:
            status = ProvenanceStatus.INVALID
            exclusion_reason = "missing_required_fields_or_unparseable_published_at"
        elif is_synthetic_fixture_url(url, source):
            status = ProvenanceStatus.SYNTHETIC_FIXTURE
            exclusion_reason = "synthetic_seed_slug_url_not_collected_from_gdelt_or_rss"
            synthetic_rows_sample.append(
                {
                    "row_index": str(idx),
                    "published_at": pub_raw,
                    "source": source,
                    "url": url,
                    "title": title,
                }
            )
        elif canonical_url in seen_urls or (norm_title, pub_day) in seen_title_days:
            status = ProvenanceStatus.DUPLICATE
            exclusion_reason = "duplicate_canonical_url_or_same_day_headline"
        else:
            seen_urls.add(canonical_url)
            if norm_title and pub_day:
                seen_title_days.add((norm_title, pub_day))

            matched_first_seen = (
                first_seen_dt.isoformat()
                if first_seen_dt is not None
                else live_by_url.get(canonical_url, "")
            )
            if matched_first_seen:
                first_seen_raw = matched_first_seen
                status = ProvenanceStatus.VERIFIED_SOURCE
                verified_dates.append(pub_dt)
            else:
                # F-04: Never backfill first_seen_at from published_at or legacy last-seen ingested_at.
                first_seen_raw = ""
                status = ProvenanceStatus.HISTORICAL_UNVERIFIED_AVAILABILITY
                exclusion_reason = "missing_genuine_first_seen_at_timestamp"
                historical_dates.append(pub_dt)

            cluster_ids_eligible.add(story_cluster_id)

        status_counts[status.value] += 1
        lang_counts[lang_norm] += 1
        if exclusion_reason:
            exclusion_counts[exclusion_reason] += 1

        audited_rows.append(
            {
                "published_at": pub_dt.isoformat() if pub_dt else pub_raw,
                "first_seen_at": first_seen_raw,
                "title": title,
                "url": url,
                "canonical_url": canonical_url,
                "source": source,
                "language_raw": lang_raw,
                "language": lang_norm,
                "content_fingerprint": fingerprint,
                "story_cluster_id": story_cluster_id,
                "cluster_key": cluster_key,
                "cluster_version": CLUSTER_VERSION,
                "provenance_status": status.value,
                "exclusion_reason": exclusion_reason,
                "query_id": (row.get("query_id") or "legacy_archive").strip(),
                "query_version": (row.get("query_version") or QUERY_VERSION).strip(),
                "collector_version": (row.get("collector_version") or "LEGACY_V1").strip(),
            }
        )

    # Apply sliding-proximity clustering across bucket boundaries (F-15/F-16)
    eligible_indices = [
        i
        for i, r in enumerate(audited_rows)
        if r["provenance_status"]
        in {
            ProvenanceStatus.VERIFIED_SOURCE.value,
            ProvenanceStatus.HISTORICAL_UNVERIFIED_AVAILABILITY.value,
        }
    ]
    if eligible_indices:
        clustered_subset = assign_story_clusters([audited_rows[i] for i in eligible_indices])
        cluster_ids_eligible.clear()
        for orig_i, crow in zip(eligible_indices, clustered_subset):
            audited_rows[orig_i]["story_cluster_id"] = crow["story_cluster_id"]
            audited_rows[orig_i]["cluster_key"] = crow["cluster_key"]
            audited_rows[orig_i]["cluster_version"] = crow["cluster_version"]
            cluster_ids_eligible.add(crow["story_cluster_id"])

    output_audited_path.parent.mkdir(parents=True, exist_ok=True)
    with output_audited_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=AUDITED_COLUMNS)
        writer.writeheader()
        writer.writerows(audited_rows)

    all_pub_dates = [
        dt for dt in (parse_utc_iso(r["published_at"]) for r in audited_rows) if dt is not None
    ]
    summary = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "raw_archive_path": str(raw_archive_path),
        "audited_archive_path": str(output_audited_path),
        "total_raw_rows": len(raw_rows),
        "status_counts": dict(status_counts),
        "exclusion_counts": dict(exclusion_counts),
        "distinct_story_clusters_non_excluded": len(cluster_ids_eligible),
        "normalized_languages_count": len(lang_counts),
        "top_languages": dict(lang_counts.most_common(12)),
        "earliest_published_at": min(all_pub_dates).isoformat() if all_pub_dates else None,
        "latest_published_at": max(all_pub_dates).isoformat() if all_pub_dates else None,
        "verified_first_seen_count": status_counts[ProvenanceStatus.VERIFIED_SOURCE.value],
        "synthetic_fixture_rows": synthetic_rows_sample,
        "collector_version": COLLECTOR_VERSION,
        "cluster_version": CLUSTER_VERSION,
        "query_version": QUERY_VERSION,
    }

    if report_md_path is not None:
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# VMD Bullion News Archive Audit & Provenance Remediation Report",
            "",
            f"- **Audited at (UTC):** `{summary['audited_at']}`",
            f"- **Raw Archive Preserved:** `{raw_archive_path.name}` ({summary['total_raw_rows']} rows — preserved untouched)",
            f"- **Audited Output:** `{output_audited_path.name}`",
            f"- **Published Range:** `{summary['earliest_published_at']}` to `{summary['latest_published_at']}`",
            f"- **Distinct Non-Fixture/Non-Duplicate Clusters (`{CLUSTER_VERSION}`):** `{summary['distinct_story_clusters_non_excluded']}`",
            "",
            "## Provenance Classification Breakdown",
            "",
            "| Provenance Status | Row Count | Share (%) | Modeling / Live Eligibility |",
            "|---|---:|---:|---|",
        ]
        total = max(1, summary["total_raw_rows"])
        notes = {
            ProvenanceStatus.VERIFIED_SOURCE.value: "Genuine collector ingest with verified `first_seen_at`; eligible for strict cutoff `T` evaluation.",
            ProvenanceStatus.HISTORICAL_UNVERIFIED_AVAILABILITY.value: "Genuine GDELT / Google News RSS record lacking `first_seen_at`; usable only for descriptive audit/human review, excluded from strict `first_seen_at <= T` availability gates.",
            ProvenanceStatus.SYNTHETIC_FIXTURE.value: "Seed fixture with fabricated bare editorial `-YYYY-MM-DD` URL slug; **strictly excluded** from features, sentiment consensus, training, and human review.",
            ProvenanceStatus.DUPLICATE.value: "Duplicate canonical URL or identical same-day normalized headline; excluded to prevent wire reprint inflation.",
            ProvenanceStatus.INVALID.value: "Missing required title/URL/timestamp; excluded.",
        }
        for key in [
            ProvenanceStatus.VERIFIED_SOURCE.value,
            ProvenanceStatus.HISTORICAL_UNVERIFIED_AVAILABILITY.value,
            ProvenanceStatus.SYNTHETIC_FIXTURE.value,
            ProvenanceStatus.DUPLICATE.value,
            ProvenanceStatus.INVALID.value,
        ]:
            cnt = status_counts.get(key, 0)
            pct = (cnt / total) * 100.0
            lines.append(f"| `{key}` | {cnt} | {pct:.2f}% | {notes[key]} |")

        lines.extend(
            [
                "",
                "## Synthetic Seed Fixtures Identified & Excluded",
                "",
                f"Detected **{len(synthetic_rows_sample)}** seed rows using synthetic bare editorial date URL slugs without publisher article IDs:",
                "",
                "| Row Index | Published At | Source | URL |",
                "|---:|---|---|---|",
            ]
        )
        for s in synthetic_rows_sample:
            lines.append(f"| {s['row_index']} | `{s['published_at']}` | `{s['source']}` | `{s['url']}` |")

        lines.extend(
            [
                "",
                "## Normalized Languages (Top 12)",
                "",
                "| Language Code | Article Count |",
                "|---|---:|",
            ]
        )
        for lang, cnt in lang_counts.most_common(12):
            lines.append(f"| `{lang}` | {cnt} |")

        lines.extend(
            [
                "",
                "## Integrity Guarantees",
                "",
                "1. Legacy `data/news/news_articles.csv` is **preserved intact** (zero rows deleted).",
                "2. `first_seen_at` is **never backfilled or reconstructed from `published_at`**.",
                "3. Only articles with genuine collector capture timestamps receive `VERIFIED_SOURCE`; legacy unverified rows are tagged `HISTORICAL_UNVERIFIED_AVAILABILITY`.",
            ]
        )
        report_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary
