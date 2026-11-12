from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bullion import BullionProduct, BullionRateObservation
from app.services.sentiment.provenance import parse_utc_iso

IST = ZoneInfo("Asia/Kolkata")

MJDTA_SPEC = {
    "product_key": "MJDTA_GOLD_24K",
    "city_code": "CHENNAI",
    "source_product_id": "MJDTA_GOLD",
    "tax_basis": "EXCL_GST",
    "purity": 0.999,
    "unit": "INR_PER_1G",
    "source_system": "KJPL_MJDTA",
}

_CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)


@dataclass(frozen=True)
class MjdtaObservation:
    sequence_index: int
    observed_at_utc: datetime
    available_at_utc: datetime
    inferred_published_at_utc: datetime | None
    has_explicit_source_date: bool
    published_time_raw: str
    gold_mjdta_inr_per_g: float
    silver_mjdta_inr_per_g: float | None
    source: str
    timestamp_status: str
    is_eligible_publication: bool
    exclusion_reason: str
    observation_id: int | None = None
    is_changed: bool = True
    source_published_at_utc: datetime | None = None
    observation_kind: str = "ORIGINAL"
    revision_number: int = 1
    original_observed_at_utc: datetime | None = None
    latest_revision_observed_at_utc: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at_utc"] = self.observed_at_utc.isoformat()
        payload["available_at_utc"] = self.available_at_utc.isoformat()
        payload["inferred_published_at_utc"] = (
            self.inferred_published_at_utc.isoformat() if self.inferred_published_at_utc else ""
        )
        payload["source_published_at_utc"] = (
            self.source_published_at_utc.isoformat() if self.source_published_at_utc else ""
        )
        payload["original_observed_at_utc"] = (
            self.original_observed_at_utc.isoformat() if self.original_observed_at_utc else ""
        )
        payload["latest_revision_observed_at_utc"] = (
            self.latest_revision_observed_at_utc.isoformat() if self.latest_revision_observed_at_utc else ""
        )
        return payload


def _parse_clock_time(raw_pub: str) -> time | None:
    match = _CLOCK_RE.search(raw_pub or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3).lower()
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return time(hour=hour, minute=minute)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_raw_mjdta_sequence(
    parsed_rows: list[dict[str, Any]],
    *,
    require_explicit_timestamp: bool = False,
) -> tuple[list[MjdtaObservation], dict[str, Any]]:
    parsed_rows.sort(
        key=lambda r: (
            _to_utc(r["explicit_source_published_at"]) if r.get("explicit_source_published_at") is not None else _to_utc(r["observed_at_utc"]),
            _to_utc(r["observed_at_utc"]),
            r.get("observation_id") or 0,
        )
    )

    observations: list[MjdtaObservation] = []
    seen_explicit_pub_keys: set[tuple[str, float]] = set()
    prev_sig: tuple[str, float] | None = None
    status_counts: Counter[str] = Counter()
    eligible_seq = 0

    for item in parsed_rows:
        obs_utc: datetime = _to_utc(item["observed_at_utc"])
        obs_ist = obs_utc.astimezone(IST)
        pub_raw: str = item["published_time_raw"]
        gold_val: float = item["gold"]
        silver_val: float | None = item.get("silver")
        explicit_dt: datetime | None = item.get("explicit_source_published_at")
        if explicit_dt is None and pub_raw:
            explicit_dt = parse_utc_iso(pub_raw)

        has_explicit_date = explicit_dt is not None
        inferred_pub_utc: datetime | None = _to_utc(explicit_dt) if explicit_dt is not None else None

        if inferred_pub_utc is None and not require_explicit_timestamp:
            clock = _parse_clock_time(pub_raw)
            if clock is not None:
                inferred_ist = datetime.combine(obs_ist.date(), clock, tzinfo=IST)
                inferred_pub_utc = inferred_ist.astimezone(timezone.utc)

        pub_key = (
            inferred_pub_utc.isoformat()
            if has_explicit_date and inferred_pub_utc is not None
            else pub_raw.lower()
        )
        sig = (pub_key, round(gold_val, 2))
        is_sunday_ist = obs_ist.weekday() == 6

        if require_explicit_timestamp and not has_explicit_date:
            status = "MISSING_SOURCE_PUBLISHED_AT"
            is_eligible = False
            exclusion_reason = "missing_source_published_at_in_db_observation"
        elif has_explicit_date and sig in seen_explicit_pub_keys:
            status = "DUPLICATE_POLL_SAME_PUBLICATION"
            is_eligible = False
            exclusion_reason = "repeated_poll_of_identical_source_published_at_and_price"
        elif prev_sig is not None and sig == prev_sig:
            status = "STALE_REPEAT_CARRYOVER"
            is_eligible = False
            exclusion_reason = "exact_duplicate_published_time_and_gold_price_of_prior_observation"
        elif not has_explicit_date and is_sunday_ist:
            status = "UNCERTAIN_SOURCE_DATE"
            is_eligible = False
            exclusion_reason = "sunday_observation_with_clock_only_published_time_missing_source_date"
        elif has_explicit_date and is_sunday_ist and inferred_pub_utc is not None and inferred_pub_utc.astimezone(IST).weekday() != 6:
            status = "STALE_REPEAT_CARRYOVER"
            is_eligible = False
            exclusion_reason = "sunday_capture_carrying_prior_weekday_source_published_at"
        elif has_explicit_date:
            status = "VALID_EXPLICIT_TIMESTAMP"
            is_eligible = True
            exclusion_reason = ""
            seen_explicit_pub_keys.add(sig)
        else:
            status = "INFERRED_SAME_IST_DAY_CLOCK_ONLY"
            is_eligible = True
            exclusion_reason = ""

        prev_sig = sig
        status_counts[status] += 1
        if is_eligible:
            eligible_seq += 1

        observations.append(
            MjdtaObservation(
                sequence_index=eligible_seq if is_eligible else -1,
                observed_at_utc=obs_utc,
                available_at_utc=_to_utc(item["available_at_utc"]) if item.get("available_at_utc") is not None else obs_utc,
                inferred_published_at_utc=inferred_pub_utc,
                has_explicit_source_date=has_explicit_date,
                published_time_raw=pub_raw,
                gold_mjdta_inr_per_g=gold_val,
                silver_mjdta_inr_per_g=silver_val,
                source=item["source"],
                timestamp_status=status,
                is_eligible_publication=is_eligible,
                exclusion_reason=exclusion_reason,
                observation_id=item.get("observation_id"),
                is_changed=bool(item.get("is_changed", True)),
                source_published_at_utc=explicit_dt if has_explicit_date else None,
                observation_kind=str(item.get("observation_kind") or "ORIGINAL"),
                revision_number=int(item.get("revision_number") or 1),
                original_observed_at_utc=(
                    _to_utc(item["original_observed_at_utc"])
                    if item.get("original_observed_at_utc") is not None
                    else obs_utc
                ),
                latest_revision_observed_at_utc=(
                    _to_utc(item["latest_revision_observed_at_utc"])
                    if item.get("latest_revision_observed_at_utc") is not None
                    else obs_utc
                ),
            )
        )

    eligible_obs = [o for o in observations if o.is_eligible_publication]
    summary = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "spec": MJDTA_SPEC,
        "total_raw_rows": len(parsed_rows),
        "parsed_valid_rows": len(observations),
        "eligible_publications": len(eligible_obs),
        "excluded_observations": len(observations) - len(eligible_obs),
        "status_counts": dict(status_counts),
        "earliest_eligible_observed_at": (
            eligible_obs[0].observed_at_utc.isoformat() if eligible_obs else None
        ),
        "latest_eligible_observed_at": (
            eligible_obs[-1].observed_at_utc.isoformat() if eligible_obs else None
        ),
        "min_gold_inr_per_g": min((o.gold_mjdta_inr_per_g for o in eligible_obs), default=None),
        "max_gold_inr_per_g": max((o.gold_mjdta_inr_per_g for o in eligible_obs), default=None),
    }
    return observations, summary


def load_mjdta_observations_from_db(
    db: Session,
    *,
    as_of: datetime | None = None,
) -> tuple[list[MjdtaObservation], dict[str, Any]]:
    """
    NEW-2 / NEW-3 / A3-FINAL-3: Load authoritative MJDTA_GOLD_24K observations directly from DB,
    preserving EVERY distinct publication (even unchanged prices) while strictly
    isolating to:
      - product_id == 'MJDTA_GOLD_24K'
      - city_code == 'CHENNAI'
      - source_product_id == 'MJDTA_GOLD'
      - validation_status == 'VALID'
      - product purity == 0.9990, unit == '1g', rate_type == 'MJDTA_BENCHMARK'
    Excludes ALL_INDIA, city retail rates, MJDTA_GOLD_24K_GST, and missing source timestamps.
    When `as_of` is given, only revisions with `observed_at <= as_of` are eligible (no backward
    leakage of future corrections).
    """
    stmt = (
        select(BullionRateObservation)
        .join(BullionProduct, BullionProduct.product_id == BullionRateObservation.product_id)
        .where(
            BullionRateObservation.product_id == "MJDTA_GOLD_24K",
            BullionRateObservation.city_code == "CHENNAI",
            BullionRateObservation.source_product_id == "MJDTA_GOLD",
            BullionRateObservation.validation_status == "VALID",
            BullionProduct.purity == Decimal("0.9990"),
            BullionProduct.unit == "1g",
            BullionProduct.rate_type == "MJDTA_BENCHMARK",
            # A3-11: the observation row itself must also be a 1g MJDTA benchmark quote.
            BullionRateObservation.unit == "1g",
            BullionRateObservation.rate_type == "MJDTA_BENCHMARK",
            BullionRateObservation.source_published_at.is_not(None),
        )
    )
    if as_of is not None:
        stmt = stmt.where(BullionRateObservation.observed_at <= _to_utc(as_of))
    stmt = stmt.order_by(
        BullionRateObservation.source_published_at.asc(),
        BullionRateObservation.revision_number.asc(),
        BullionRateObservation.observed_at.asc(),
        BullionRateObservation.id.asc(),
    )
    all_rows = db.execute(stmt).scalars().all()

    # A3-10 / A3-FINAL-3: Group by distinct source_published_at. Keep original arrival time
    # (`observed_at_utc`) on the earliest row while selecting the highest revision_number
    # available as of `as_of` for the authoritative price.
    grouped_by_pub: dict[datetime, list[Any]] = {}
    superseded = 0
    for row in all_rows:
        key = _to_utc(row.source_published_at)
        grouped_by_pub.setdefault(key, []).append(row)

    parsed_rows: list[dict[str, Any]] = []
    for key in sorted(grouped_by_pub):
        revs = grouped_by_pub[key]
        if len(revs) > 1:
            superseded += len(revs) - 1
        orig_row = revs[0]
        selected_row = revs[-1]
        price_val = float(selected_row.normalized_price_per_gram or selected_row.price)
        if price_val <= 0:
            continue
        orig_obs_dt = _to_utc(orig_row.observed_at)
        sel_obs_dt = _to_utc(selected_row.observed_at)
        src_pub = _to_utc(selected_row.source_published_at) if selected_row.source_published_at is not None else None
        parsed_rows.append(
            {
                "observation_id": selected_row.id,
                "observed_at_utc": orig_obs_dt,
                "available_at_utc": max(orig_obs_dt, sel_obs_dt),
                "original_observed_at_utc": orig_obs_dt,
                "latest_revision_observed_at_utc": sel_obs_dt,
                "explicit_source_published_at": src_pub,
                "published_time_raw": src_pub.isoformat() if src_pub is not None else "",
                "gold": price_val,
                "silver": None,
                "source": selected_row.source_name or "KJPL",
                "is_changed": bool(selected_row.is_changed),
                "observation_kind": str(getattr(selected_row, "observation_kind", "ORIGINAL") or "ORIGINAL"),
                "revision_number": int(getattr(selected_row, "revision_number", 1) or 1),
            }
        )

    observations, summary = _normalize_raw_mjdta_sequence(parsed_rows, require_explicit_timestamp=True)
    summary["source_backend"] = "database"
    summary["superseded_same_publication_rows"] = superseded
    return observations, summary


def load_and_audit_mjdta_series(
    kjpl_csv_path: Path,
    audited_csv_output: Path | None = None,
    report_md_path: Path | None = None,
) -> tuple[list[MjdtaObservation], dict[str, Any]]:
    """
    Audit legacy KJPL MJDTA CSV (`data/kjpl/kjpl_rates.csv`) without deleting rows.
    Intended strictly for legacy archive auditing and DB migration backfill — NOT live runtime fallback.
    """
    if not kjpl_csv_path.exists():
        raise FileNotFoundError(f"MJDTA CSV not found: {kjpl_csv_path}")

    with kjpl_csv_path.open("r", encoding="utf-8") as fh:
        raw_rows = list(csv.DictReader(fh))

    parsed_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        obs_dt = parse_utc_iso(row.get("observed_at"))
        if obs_dt is None:
            continue
        try:
            gold_val = float(row["gold_mjdta"])
        except Exception:
            continue
        silver_raw = row.get("silver_mjdta")
        try:
            silver_val = float(silver_raw) if silver_raw not in (None, "") else None
        except Exception:
            silver_val = None
        if gold_val <= 0:
            continue
        parsed_rows.append(
            {
                "observation_id": None,
                "observed_at_utc": obs_dt,
                "explicit_source_published_at": None,
                "published_time_raw": (row.get("published_time") or "").strip(),
                "gold": gold_val,
                "silver": silver_val,
                "source": (row.get("source") or "KJPL").strip(),
                "is_changed": True,
            }
        )

    observations, summary = _normalize_raw_mjdta_sequence(parsed_rows, require_explicit_timestamp=False)
    summary["source_backend"] = "legacy_csv_archive"
    summary["total_raw_rows"] = len(raw_rows)

    if audited_csv_output is not None:
        audited_csv_output.parent.mkdir(parents=True, exist_ok=True)
        cols = [
            "observation_id",
            "sequence_index",
            "observed_at_utc",
            "available_at_utc",
            "inferred_published_at_utc",
            "has_explicit_source_date",
            "published_time_raw",
            "gold_mjdta_inr_per_g",
            "silver_mjdta_inr_per_g",
            "source",
            "timestamp_status",
            "is_eligible_publication",
            "is_changed",
            "exclusion_reason",
        ]
        with audited_csv_output.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            for obs in observations:
                writer.writerow(obs.to_dict())

    if report_md_path is not None:
        report_md_path.parent.mkdir(parents=True, exist_ok=True)
        status_counts = summary["status_counts"]
        lines = [
            "# MJDTA Target Series Audit & Timestamp Remediation Report",
            "",
            f"- **Audited at (UTC):** `{summary['audited_at']}`",
            f"- **Target Specification:** `{MJDTA_SPEC['product_key']}` (`city_code=CHENNAI`, `source_product_id=MJDTA_GOLD`, `{MJDTA_SPEC['tax_basis']}`, Purity `{MJDTA_SPEC['purity']}`, Unit `{MJDTA_SPEC['unit']}`)",
            "- **Authoritative Live/Prospective Source:** PostgreSQL / Neon `bullion_rate_observations` (`MJDTA_GOLD_24K`, `CHENNAI`, `MJDTA_GOLD`, `validation_status='VALID'`).",
            f"- **Legacy Frozen CSV Preserved (`kjpl_rates.csv`):** {summary['total_raw_rows']} rows ({summary['eligible_publications']} eligible publications; {summary['excluded_observations']} excluded Sunday/carry-over anomalies).",
            f"- **Legacy CSV Date Range:** `{summary['earliest_eligible_observed_at']}` to `{summary['latest_eligible_observed_at']}`",
            f"- **Legacy Price Range (`INR/1g`):** `{summary['min_gold_inr_per_g']}` – `{summary['max_gold_inr_per_g']}`",
            "",
            "## Legacy Archive Timestamp & Carry-Over Breakdown",
            "",
            "| Timestamp Status | Count | Action |",
            "|---|---:|---|",
        ]
        for st, cnt in status_counts.items():
            action = (
                "Included (availability gated by `observed_at_utc`)"
                if st in {"VALID_EXPLICIT_TIMESTAMP", "INFERRED_SAME_IST_DAY_CLOCK_ONLY"}
                else "Excluded from target series (preserved in raw CSV)"
            )
            lines.append(f"| `{st}` | {cnt} | {action} |")

        flagged = [o for o in observations if not o.is_eligible_publication]
        lines.extend(
            [
                "",
                "## Excluded / Uncertain Observations (Legacy CSV)",
                "",
                "| Observed At (UTC) | Raw Published Time | Gold (INR/g) | Status | Reason |",
                "|---|---|---:|---|---|",
            ]
        )
        for o in flagged:
            lines.append(
                f"| `{o.observed_at_utc.isoformat()}` | `{o.published_time_raw}` | {o.gold_mjdta_inr_per_g:.2f} | `{o.timestamp_status}` | `{o.exclusion_reason}` |"
            )

        lines.extend(
            [
                "",
                "## Continuity, Isolation & Publication Guarantees",
                "",
                "1. Every distinct genuine MJDTA publication (`source_published_at`) is persisted as a `VALID` observation even when the published price is unchanged (`is_changed=False`).",
                "2. Production MJDTA reads are strictly isolated to `city_code='CHENNAI'`, `product_id='MJDTA_GOLD_24K'`, `source_product_id='MJDTA_GOLD'`, excluding `ALL_INDIA`, retail city quotes, and GST-included benchmarks.",
                "3. Observations missing `source_published_at` are quarantined/excluded rather than fabricated from `observed_at`.",
            ]
        )
        report_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return observations, summary
