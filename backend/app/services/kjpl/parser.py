from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .schemas import KJPLRate
from .validator import validate_bullion_observation


IST = ZoneInfo("Asia/Kolkata")


def _extract_number(text: str) -> float | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def parse_full_kjpl_datetime(text: str | None) -> datetime | None:
    """
    Parse explicit KJPL date+time strings such as:
      - '11-11-2026 09:37:32 am'
      - '11-11-2026 09:37 am'
      - '11/11/2026 02:01:59 PM'
    Returns a timezone-aware datetime in Asia/Kolkata, or None if no full date is present.
    """
    if not text:
        return None
    clean = text.strip().strip('"').strip()
    for fmt in (
        "%d-%m-%Y %I:%M:%S %p",
        "%d-%m-%Y %I:%M %p",
        "%d/%m/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _parse_source_updated_at(
    source_updated_time: str | None,
    full_updated_text: str | None = None,
) -> datetime | None:
    """
    Prefer the explicit full date+time timestamp published in KJPL's MJDTA table
    (e.g. '11-11-2026 09:37:32 am'). Fall back to clock-only parsing only when
    explicit full date+time is unavailable.
    """
    if full_updated_text:
        full_dt = parse_full_kjpl_datetime(full_updated_text)
        if full_dt is not None:
            return full_dt

    if not source_updated_time:
        return None

    return resolve_clock_only_kjpl_time(source_updated_time, datetime.now(IST))


@dataclass(frozen=True)
class ClockResolution:
    timestamp_ist: datetime | None
    precision_status: str  # INFERRED_CLOCK_ONLY | AMBIGUOUS_CLOCK_ONLY | INVALID_CLOCK
    is_inferred: bool
    is_pre_open_carryover: bool
    reason: str


def resolve_clock_only_kjpl_timestamp(time_str: str | None, now_ist: datetime) -> ClockResolution:
    """
    Resolve a clock-only 'HH:MM am/pm' string WITHOUT inventing a publication date or
    allowing source_published_at > observed_at:
      - Same-day clock <= now_ist -> today (INFERRED_CLOCK_ONLY)
      - Midnight crossing (now_ist in 00:00..05:59, clock in 18:00..23:59) -> yesterday (INFERRED_CLOCK_ONLY)
      - Pre-open morning poll (now_ist < 09:00, clock >= 09:00, >=2h ahead) -> prior-day carryover candidate
        (persistence verifies established DB carryover or quarantines)
      - Any other future clock (e.g. 1..30 min ahead) -> None / AMBIGUOUS_CLOCK_ONLY (must quarantine)
    """
    if not time_str:
        return ClockResolution(None, "MISSING", False, False, "empty_clock_text")
    match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_str, re.IGNORECASE)
    if not match:
        return ClockResolution(None, "INVALID_CLOCK", False, False, "unparseable_clock_text")
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3).lower()
    if hour > 12 or minute > 59:
        return ClockResolution(None, "INVALID_CLOCK", False, False, "invalid_hour_or_minute")
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    now_local = now_ist.astimezone(IST) if now_ist.tzinfo else now_ist.replace(tzinfo=IST)
    same_day = datetime(now_local.year, now_local.month, now_local.day, hour, minute, tzinfo=IST)

    if same_day <= now_local:
        return ClockResolution(same_day, "INFERRED_CLOCK_ONLY", True, False, "same_day_not_future")

    # True midnight crossing (e.g. 00:10 IST reading 11:50 pm from previous evening)
    if now_local.hour < 6 and same_day.hour >= 18:
        return ClockResolution(
            same_day - timedelta(days=1),
            "INFERRED_CLOCK_ONLY",
            True,
            False,
            "midnight_crossing_previous_day",
        )

    # Pre-morning-open poll (>=2h before 09:00+ schedule) -> candidate carryover requiring DB proof
    if now_local.hour < 9 and same_day.hour >= 9 and (same_day - now_local) >= timedelta(hours=2):
        return ClockResolution(
            same_day - timedelta(days=1),
            "INFERRED_CLOCK_ONLY",
            True,
            True,
            "pre_open_morning_carryover_candidate",
        )

    # Arbitrary clock ahead of collection time (e.g. 1, 5, 6, 10, 30 min): DO NOT GUESS
    return ClockResolution(
        None,
        "AMBIGUOUS_CLOCK_ONLY",
        True,
        False,
        f"clock_ahead_of_observation_by_{int((same_day - now_local).total_seconds())}s",
    )


def resolve_clock_only_kjpl_time(time_str: str | None, now_ist: datetime) -> datetime | None:
    """Resolve a clock-only 'HH:MM am/pm' string safely; returns None when ambiguous."""
    return resolve_clock_only_kjpl_timestamp(time_str, now_ist).timestamp_ist


def _extract_mjdta_tables(soup: BeautifulSoup) -> dict[str, str | float | None]:
    """
    Extract structured fields exclusively from KJPL's .chennairate_table MJDTA blocks,
    avoiding LBMA London USD/oz tables and combined header tables.
    """
    out: dict[str, str | float | None] = {
        "gold_no_gst": None,
        "silver_no_gst": None,
        "gold_with_gst": None,
        "silver_with_gst": None,
        "updated_full": None,
    }

    for table in soup.find_all("table"):
        text_upper = table.get_text(" ", strip=True).upper()
        is_with_gst = "MJDTA RATE (WITH GST)" in text_upper
        is_without_gst = "MJDTA RATE (WITHOUT GST)" in text_upper
        if not (is_with_gst or is_without_gst):
            continue

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_text = " ".join(c.get_text(" ", strip=True) for c in cells)
            row_upper = row_text.upper()

            if "UPDATED" in row_upper and len(cells) >= 2:
                cand = cells[-1].get_text(" ", strip=True)
                if parse_full_kjpl_datetime(cand) is not None:
                    out["updated_full"] = cand
                continue

            val = _extract_number(cells[-1].get_text(" ", strip=True))
            if val is None:
                continue

            if "GOLD" in row_upper and "SILVER" not in row_upper:
                key = "gold_with_gst" if is_with_gst else "gold_no_gst"
                if out[key] is None:
                    out[key] = val
            elif "SILVER" in row_upper and "GOLD" not in row_upper:
                key = "silver_with_gst" if is_with_gst else "silver_no_gst"
                if out[key] is None:
                    out[key] = val

    return out


def _extract_gold_with_gst(soup: BeautifulSoup) -> float | None:
    val = _extract_mjdta_tables(soup).get("gold_with_gst")
    return float(val) if isinstance(val, (int, float)) else None


def parse_kjpl_html(html: str) -> KJPLRate:
    soup = BeautifulSoup(html, "html.parser")
    table_data = _extract_mjdta_tables(soup)

    gold_element = soup.select_one(".gold-rate")
    silver_element = soup.select_one(".silver-rate")
    time_element = soup.select_one(".mjdma_data")

    gold_mjdta = (
        _extract_number(gold_element.get_text(" ", strip=True))
        if gold_element
        else table_data.get("gold_no_gst")
    )
    if not isinstance(gold_mjdta, (int, float)):
        raise ValueError("KJPL MJDTA gold rate not found. The website structure may have changed.")

    gold_val = validate_bullion_observation(
        product_id="MJDTA_GOLD_24K",
        metal="GOLD",
        currency="INR",
        unit="1g",
        weight_value=1.0,
        price=float(gold_mjdta),
    )
    if gold_val.validation_status == "QUARANTINED":
        raise ValueError(f"Invalid KJPL MJDTA gold rate: {gold_val.reason}")

    silver_raw = (
        _extract_number(silver_element.get_text(" ", strip=True))
        if silver_element
        else table_data.get("silver_no_gst")
    )
    silver_mjdta: float | None = None
    if isinstance(silver_raw, (int, float)):
        silver_val = validate_bullion_observation(
            product_id="MJDTA_SILVER",
            metal="SILVER",
            currency="INR",
            unit="1g",
            weight_value=1.0,
            price=float(silver_raw),
        )
        if silver_val.validation_status != "QUARANTINED":
            silver_mjdta = float(silver_raw)

    source_updated_time = (
        str(table_data["updated_full"])
        if table_data.get("updated_full")
        else (time_element.get_text(" ", strip=True) if time_element else None)
    )
    source_updated_at = _parse_source_updated_at(
        source_updated_time,
        full_updated_text=str(table_data["updated_full"]) if table_data.get("updated_full") else None,
    )

    gold_with_gst_raw = table_data.get("gold_with_gst")
    gold_with_gst = float(gold_with_gst_raw) if isinstance(gold_with_gst_raw, (int, float)) else None

    return KJPLRate(
        gold_mjdta=float(gold_mjdta),
        silver_mjdta=silver_mjdta,
        gold_with_gst=gold_with_gst,
        source_updated_time=source_updated_time,
        source_updated_at=source_updated_at,
        observed_at=datetime.now(IST),
    )
