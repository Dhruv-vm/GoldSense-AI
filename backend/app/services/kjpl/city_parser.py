from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from app.services.kjpl.city_schemas import ParsedCityRate, ParsedKJPLPayload

IST = ZoneInfo("Asia/Kolkata")

# Canonical 5 Mandatory Cities Mapping
CITY_MAPPINGS: dict[str, tuple[str, str]] = {
    # key (normalized lowercase pattern) -> (canonical_city_code, display_name)
    "chennai": ("CHENNAI", "Chennai"),
    "bangalore": ("BENGALURU", "Bengaluru"),  # Strictly normalize Bangalore to Bengaluru
    "bengaluru": ("BENGALURU", "Bengaluru"),
    "mumbai": ("MUMBAI", "Mumbai"),
    "coimbatore": ("COIMBATORE", "Coimbatore"),
    "hyderabad": ("HYDERABAD", "Hyderabad"),
}

# Known Commodity ID map from KJPL live engine
KNOWN_COM_ID_MAP: dict[str, dict[str, Any]] = {
    "47": {
        "city_code": "ALL_INDIA",
        "city_display_name": "National",
        "product_id": "GOLD_1KG_9999",
        "product_name": "Gold 1KG 99.99 Pure Bar",
        "metal": "GOLD",
        "purity": 0.9999,
        "weight": 1.0,
        "unit": "1kg",
        "rate_type": "WHOLESALE",
    },
    "48": {
        "city_code": "CHENNAI",
        "city_display_name": "Chennai",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Chennai",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 100.0,
        "unit": "100g",
        "rate_type": "RETAIL",
    },
    "49": {
        "city_code": "BENGALURU",
        "city_display_name": "Bengaluru",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Bengaluru",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 100.0,
        "unit": "100g",
        "rate_type": "RETAIL",
    },
    "50": {
        "city_code": "MUMBAI",
        "city_display_name": "Mumbai",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Mumbai",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 100.0,
        "unit": "100g",
        "rate_type": "RETAIL",
    },
    "51": {
        "city_code": "COIMBATORE",
        "city_display_name": "Coimbatore",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Coimbatore",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 100.0,
        "unit": "100g",
        "rate_type": "RETAIL",
    },
    "52": {
        "city_code": "HYDERABAD",
        "city_display_name": "Hyderabad",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Hyderabad",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 100.0,
        "unit": "100g",
        "rate_type": "RETAIL",
    },
    "2": {
        "city_code": "ALL_INDIA",
        "city_display_name": "National",
        "product_id": "MJDTA_SILVER",
        "product_name": "Spot Silver Benchmark",
        "metal": "SILVER",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1g",
        "rate_type": "MJDTA_BENCHMARK",
    },
    "12": {
        "city_code": "CHENNAI",
        "city_display_name": "Chennai",
        "product_id": "SILVER_1KG_999",
        "product_name": "Silver 1KG 999 Chennai",
        "metal": "SILVER",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1kg",
        "rate_type": "RETAIL",
    },
}


def _extract_number(text: str | None) -> float | None:
    if not text:
        return None
    clean = text.replace(",", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", clean)
    if not match:
        return None
    val = float(match.group(0))
    return val if val > 0 else None


def _parse_source_clock_time(time_str: str | None, now_ist: datetime) -> datetime | None:
    if not time_str:
        return None
    match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_str, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return datetime(
        year=now_ist.year,
        month=now_ist.month,
        day=now_ist.day,
        hour=hour,
        minute=minute,
        tzinfo=IST,
    )


def _resolve_city_and_product(name: str, com_id: str | None = None) -> dict[str, Any]:
    """
    Given a raw product string (and optional com_id), deduce city, product_id, metal,
    purity, weight, unit, and rate_type.
    """
    if com_id and com_id in KNOWN_COM_ID_MAP:
        meta = dict(KNOWN_COM_ID_MAP[com_id])
        return meta

    upper_name = name.upper()
    metal = "SILVER" if "SILVER" in upper_name else "GOLD"

    # Identify city
    city_code = "ALL_INDIA"
    city_display = "National"
    for k, (code, display) in CITY_MAPPINGS.items():
        if k.upper() in upper_name:
            city_code = code
            city_display = display
            break

    # Identify purity & weight
    if "1KG" in upper_name or "1 KG" in upper_name or "1000" in upper_name:
        weight = 1.0
        unit = "1kg"
        purity = 0.9999 if "99.99" in upper_name or "9999" in upper_name else 0.999
        product_id = f"{metal}_1KG_9999" if purity == 0.9999 else f"{metal}_1KG_999"
        rate_type = "WHOLESALE"
    elif "100" in upper_name:
        weight = 100.0
        unit = "100g"
        purity = 0.999
        product_id = f"{metal}_100G_999"
        rate_type = "RETAIL"
    else:
        weight = 1.0
        unit = "1g"
        purity = 0.999
        product_id = f"MJDTA_{metal}_24K" if metal == "GOLD" else f"MJDTA_{metal}"
        rate_type = "MJDTA_BENCHMARK"

    return {
        "city_code": city_code,
        "city_display_name": city_display,
        "product_id": product_id,
        "product_name": name,
        "metal": metal,
        "purity": purity,
        "weight": weight,
        "unit": unit,
        "rate_type": rate_type,
    }


def parse_kjpl_all_city_rates(html_content: str, reference_time: datetime | None = None) -> ParsedKJPLPayload:
    """
    Comprehensive parsing engine for KJPL Bullion.
    Extracts:
      1. Benchmark MJDTA Gold & Silver (without GST and with GST).
      2. Product rows from HTML tables.
      3. Embedded JSON payloads / script tags (JSON data feed).
      4. City-specific products for Chennai, Bengaluru, Mumbai, Coimbatore, Hyderabad.
    """
    now = reference_time or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)

    soup = BeautifulSoup(html_content, "html.parser")
    errors: list[str] = []

    # 1. Benchmark Rates from .gold-rate, .silver-rate, .mjdma_data
    gold_elem = soup.select_one(".gold-rate")
    silver_elem = soup.select_one(".silver-rate")
    time_elem = soup.select_one(".mjdma_data")

    mjdta_gold = _extract_number(gold_elem.get_text(strip=True)) if gold_elem else None
    mjdta_silver = _extract_number(silver_elem.get_text(strip=True)) if silver_elem else None
    source_clock_time = time_elem.get_text(" ", strip=True) if time_elem else None
    source_published_at = _parse_source_clock_time(source_clock_time, now)

    # 2. Check MJDTA with GST Table
    mjdta_gold_with_gst = None
    mjdta_silver_with_gst = None
    for strong in soup.find_all("strong"):
        text = strong.get_text(strip=True).upper()
        if "MJDTA RATE (WITH GST)" in text:
            table = strong.find_parent("table")
            if table:
                for row in table.find_all("tr"):
                    cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                    row_str = " ".join(cells).upper()
                    if "GOLD" in row_str:
                        val = _extract_number(row_str)
                        if val and val > 1000:
                            mjdta_gold_with_gst = val
                    elif "SILVER" in row_str:
                        val = _extract_number(row_str)
                        if val:
                            mjdta_silver_with_gst = val

    city_rates_dict: dict[tuple[str, str], ParsedCityRate] = {}

    # 3. Strategy A: Embedded JSON in <script> or JSON tags
    for script in soup.find_all("script"):
        content = script.string or ""
        if "com_name" in content or "sellrate" in content:
            # Try parsing direct JSON or regex matching JSON arrays
            json_matches = re.findall(r"\[\s*\{.*?\"com_name\".*?\}\s*\]", content, re.DOTALL)
            for jm in json_matches:
                try:
                    data = json.loads(jm)
                    for item in data:
                        com_id = str(item.get("com_id", "")).strip()
                        raw_name = str(item.get("com_name", "")).strip()
                        raw_sellrate = str(item.get("sellrate", "")).strip()
                        raw_diff = str(item.get("selldiff", "0")).strip()
                        price = _extract_number(raw_sellrate)
                        diff_val = _extract_number(raw_diff)
                        if not price or not raw_name:
                            continue

                        resolved = _resolve_city_and_product(raw_name, com_id)
                        key = (resolved["city_code"], resolved["product_id"])
                        city_rates_dict[key] = ParsedCityRate(
                            city_code=resolved["city_code"],
                            city_display_name=resolved["city_display_name"],
                            product_id=resolved["product_id"],
                            product_name=resolved["product_name"],
                            metal=resolved["metal"],
                            purity=resolved["purity"],
                            weight=resolved["weight"],
                            unit=resolved["unit"],
                            rate_type=resolved["rate_type"],
                            price=price,
                            currency="INR",
                            source_product_id=com_id or None,
                            raw_source_name=raw_name,
                            diff_rate=diff_val,
                        )
                except Exception as e:
                    errors.append(f"JSON script parse error: {e}")

    # 4. Strategy B: HTML Tables with product rows (TRs with data attributes or product text)
    table_rows = soup.find_all("tr")
    for tr in table_rows:
        com_id = tr.get("data-com-id") or tr.get("id")
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells or len(cells) < 2:
            continue

        row_text = " ".join(cells)
        # Check if row looks like a bullion product
        is_bullion_row = any(w in row_text.upper() for w in ["GOLD", "SILVER", "MJDTA", "CHENNAI", "BANGALORE", "MUMBAI", "COIMBATORE", "HYDERABAD"])
        if not is_bullion_row:
            continue

        raw_name = cells[0]
        # Identify price cell: usually last or cell with largest numerical value
        numbers = [_extract_number(c) for c in cells]
        valid_numbers = [n for n in numbers if n is not None and n > 50.0]
        if not valid_numbers:
            continue

        price = valid_numbers[-1]  # rate is typically the last column
        resolved = _resolve_city_and_product(raw_name, str(com_id) if com_id else None)
        key = (resolved["city_code"], resolved["product_id"])

        if key not in city_rates_dict:
            city_rates_dict[key] = ParsedCityRate(
                city_code=resolved["city_code"],
                city_display_name=resolved["city_display_name"],
                product_id=resolved["product_id"],
                product_name=resolved["product_name"],
                metal=resolved["metal"],
                purity=resolved["purity"],
                weight=resolved["weight"],
                unit=resolved["unit"],
                rate_type=resolved["rate_type"],
                price=price,
                currency="INR",
                source_product_id=str(com_id) if com_id else None,
                raw_source_name=raw_name,
            )

    # 5. Always include MJDTA reference rates if parsed and not yet in dict
    if mjdta_gold:
        gold_key = ("CHENNAI", "MJDTA_GOLD_24K")
        if gold_key not in city_rates_dict:
            city_rates_dict[gold_key] = ParsedCityRate(
                city_code="CHENNAI",
                city_display_name="Chennai",
                product_id="MJDTA_GOLD_24K",
                product_name="MJDTA Gold 24K Pure (Chennai Benchmark)",
                metal="GOLD",
                purity=0.999,
                weight=1.0,
                unit="1g",
                rate_type="MJDTA_BENCHMARK",
                price=mjdta_gold,
                currency="INR",
                source_product_id="MJDTA_GOLD",
                raw_source_name="Gold MJDTA",
            )
    if mjdta_silver:
        silver_key = ("CHENNAI", "MJDTA_SILVER")
        if silver_key not in city_rates_dict:
            city_rates_dict[silver_key] = ParsedCityRate(
                city_code="CHENNAI",
                city_display_name="Chennai",
                product_id="MJDTA_SILVER",
                product_name="MJDTA Silver Benchmark (Chennai)",
                metal="SILVER",
                purity=0.999,
                weight=1.0,
                unit="1g",
                rate_type="MJDTA_BENCHMARK",
                price=mjdta_silver,
                currency="INR",
                source_product_id="2",
                raw_source_name="Silver MJDTA",
            )

    sorted_rates = sorted(city_rates_dict.values(), key=lambda r: (r.metal, r.city_code, r.product_id))

    return ParsedKJPLPayload(
        observed_at=now,
        source_updated_time=source_clock_time,
        source_updated_at=source_published_at,
        mjdta_gold=mjdta_gold,
        mjdta_silver=mjdta_silver,
        mjdta_gold_with_gst=mjdta_gold_with_gst,
        mjdta_silver_with_gst=mjdta_silver_with_gst,
        city_rates=sorted_rates,
        raw_products_count=len(sorted_rates),
        extraction_errors=errors,
    )
