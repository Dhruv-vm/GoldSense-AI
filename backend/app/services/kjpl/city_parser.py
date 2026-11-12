from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from app.services.kjpl.city_schemas import ParsedCityRate, ParsedKJPLPayload
from app.services.kjpl.parser import (
    _extract_mjdta_tables,
    parse_full_kjpl_datetime,
    parse_kjpl_type4_datetime,
    resolve_clock_only_kjpl_time,
    resolve_clock_only_kjpl_timestamp,
)
from app.services.kjpl.validator import validate_bullion_observation, resolve_weight_grams

IST = ZoneInfo("Asia/Kolkata")

CITY_MAPPINGS: dict[str, tuple[str, str]] = {
    "chennai": ("CHENNAI", "Chennai"),
    "bangalore": ("BENGALURU", "Bengaluru"),
    "bengaluru": ("BENGALURU", "Bengaluru"),
    "mumbai": ("MUMBAI", "Mumbai"),
    "coimbatore": ("COIMBATORE", "Coimbatore"),
    "hyderabad": ("HYDERABAD", "Hyderabad"),
}

# Verified KJPL commodity metadata (verified 2026-11-11 via get_rpanel_data + kjpl.txt + ws://www.kjpl.in/ws)
LIVE_TYPE3_COM_ID_MAP: dict[str, dict[str, Any]] = {
    "47": {
        "city_code": "ALL_INDIA",
        "city_display_name": "National",
        "product_id": "GOLD_1KG_9999",
        "product_name": "GOLD 1KG 99.99",
        "metal": "GOLD",
        "purity": 0.9999,
        "weight": 1.0,
        "unit": "1g",  # Live feed com_weight=1.000 quotes INR/1g
        "rate_type": "WHOLESALE",
    },
    "48": {
        "city_code": "CHENNAI",
        "city_display_name": "Chennai",
        "product_id": "GOLD_100G_999",
        "product_name": "GOLD 100 GMS 999 Chennai",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1g",
        "rate_type": "RETAIL",
    },
    "49": {
        "city_code": "BENGALURU",
        "city_display_name": "Bengaluru",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Bengaluru",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1g",
        "rate_type": "RETAIL",
    },
    "50": {
        "city_code": "MUMBAI",
        "city_display_name": "Mumbai",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Mumbai",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1g",
        "rate_type": "RETAIL",
    },
    "51": {
        "city_code": "COIMBATORE",
        "city_display_name": "Coimbatore",
        "product_id": "GOLD_100G_999",
        "product_name": "Gold 100 GMS 999 Coimbatore",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1g",
        "rate_type": "RETAIL",
    },
    "52": {
        "city_code": "HYDERABAD",
        "city_display_name": "Hyderabad",
        "product_id": "GOLD_100G_999",
        "product_name": "GOLD 100 GMS 999 Hyderabad",
        "metal": "GOLD",
        "purity": 0.999,
        "weight": 1.0,
        "unit": "1g",
        "rate_type": "RETAIL",
    },
}


def _extract_number(text: str | None) -> float | None:
    if not text:
        return None
    clean = text.replace(",", "").strip()
    if clean in ("-", "--", ""):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", clean)
    if not match:
        return None
    val = float(match.group(0))
    return val if val > 0 else None


def _parse_source_clock_time(
    time_str: str | None,
    now_ist: datetime,
    full_updated_text: str | None = None,
) -> datetime | None:
    if full_updated_text:
        full_dt = parse_full_kjpl_datetime(full_updated_text)
        if full_dt is not None:
            return full_dt
    if not time_str:
        return None
    full_inline = parse_full_kjpl_datetime(time_str)
    if full_inline is not None:
        return full_inline
    return resolve_clock_only_kjpl_time(time_str, now_ist)


def _resolve_city_and_product(name: str, com_id: str | None = None, price_hint: float | None = None) -> dict[str, Any]:
    """
    Resolve metadata from com_id / product name.
    Detects whether IDs 47..52 are quoted in per-1g live scale (<100,000) vs total bar price (>=500,000).
    """
    if com_id and com_id in LIVE_TYPE3_COM_ID_MAP:
        meta = dict(LIVE_TYPE3_COM_ID_MAP[com_id])
        if price_hint is not None and price_hint >= 500_000:
            if com_id == "47":
                meta["weight"] = 1.0
                meta["unit"] = "1kg"
            else:
                meta["weight"] = 100.0
                meta["unit"] = "100g"
        return meta

    upper_name = name.upper()
    metal = "SILVER" if "SILVER" in upper_name else "GOLD"

    city_code = "ALL_INDIA"
    city_display = "National"
    for k, (code, display) in CITY_MAPPINGS.items():
        if k.upper() in upper_name:
            city_code = code
            city_display = display
            break

    if "1KG" in upper_name or "1 KG" in upper_name or "1000" in upper_name:
        purity = 0.9999 if "99.99" in upper_name or "9999" in upper_name else 0.999
        product_id = f"{metal}_1KG_9999" if purity == 0.9999 else f"{metal}_1KG_999"
        if price_hint is not None and price_hint < 100_000 and metal == "GOLD":
            weight, unit = 1.0, "1g"
        else:
            weight, unit = 1.0, "1kg"
        rate_type = "WHOLESALE" if metal == "GOLD" else "RETAIL"
    elif "100" in upper_name:
        purity = 0.999
        product_id = f"{metal}_100G_999"
        if price_hint is not None and price_hint < 100_000 and metal == "GOLD":
            weight, unit = 1.0, "1g"
        else:
            weight, unit = 100.0, "100g"
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


def _build_validated_item(
    *,
    city_code: str,
    city_display_name: str,
    product_id: str,
    product_name: str,
    metal: str,
    purity: float,
    weight: float,
    unit: str,
    rate_type: str,
    price: float,
    currency: str = "INR",
    buy_price: float | None = None,
    high_price: float | None = None,
    low_price: float | None = None,
    source_product_id: str | None = None,
    raw_source_name: str | None = None,
    diff_rate: float | None = None,
    raw_payload_reference: str | None = None,
) -> ParsedCityRate:
    outcome = validate_bullion_observation(
        product_id=product_id,
        metal=metal,
        currency=currency,
        unit=unit,
        weight_value=weight,
        price=price,
        source_product_id=source_product_id,
    )
    return ParsedCityRate(
        city_code=city_code,
        city_display_name=city_display_name,
        product_id=product_id,
        product_name=product_name,
        metal=metal,
        purity=purity,
        weight=weight,
        unit=unit,
        product_weight_grams=outcome.product_weight_grams,
        rate_type=rate_type,
        price=price,
        buy_price=buy_price,
        high_price=high_price,
        low_price=low_price,
        normalized_price_per_gram=outcome.normalized_price_per_gram,
        currency=currency,
        source_product_id=source_product_id,
        raw_source_name=raw_source_name,
        diff_rate=diff_rate,
        validation_status=outcome.validation_status,
        quarantine_reason=outcome.reason,
        raw_payload_reference=raw_payload_reference,
    )


def parse_kjpl_live_feed(
    raw_text: str,
    rpanel_json: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    source_label: str = "KJPL_LIVE_TXT",
) -> ParsedKJPLPayload:
    """
    Parse KJPL's verified live WebSocket (pipe-delimited) or kjpl.txt (tab-delimited) payload
    alongside optional C_booking/get_rpanel_data JSON metadata.
    """
    now = reference_time or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)

    valid_items: list[ParsedCityRate] = []
    quarantined_items: list[ParsedCityRate] = []
    errors: list[str] = []

    rpanel_comms: dict[str, dict[str, Any]] = {}
    if rpanel_json and isinstance(rpanel_json.get("commoditydetails"), list):
        for c in rpanel_json["commoditydetails"]:
            cid = str(c.get("com_id", "")).strip()
            if cid:
                rpanel_comms[cid] = c

    source_updated_at: datetime | None = None
    source_updated_time: str | None = None
    market_status: str | None = None
    rate_display_enabled: bool | None = None

    type1_map = {
        "G": ("KJPL_SPOT_GOLD_USD", "KJPL Spot Gold ($)", "GOLD", "oz", "USD"),
        "SPOT-GOLD": ("KJPL_SPOT_GOLD_USD", "KJPL Spot Gold ($)", "GOLD", "oz", "USD"),
        "S": ("KJPL_SPOT_SILVER_USD", "KJPL Spot Silver ($)", "SILVER", "oz", "USD"),
        "SPOT-SILVER": ("KJPL_SPOT_SILVER_USD", "KJPL Spot Silver ($)", "SILVER", "oz", "USD"),
        "I": ("KJPL_SPOT_USDINR", "KJPL Spot USD/INR", "FX", "USD", "INR"),
        "SPOT-INR": ("KJPL_SPOT_USDINR", "KJPL Spot USD/INR", "FX", "USD", "INR"),
    }
    type2_map = {
        "GOLD": ("KJPL_GOLDDEC_INR_10G", "KJPL Gold Contract (10g)", "GOLD", 10.0, "10g"),
        "GOLDDEC": ("KJPL_GOLDDEC_INR_10G", "KJPL Gold Contract (10g)", "GOLD", 10.0, "10g"),
        "SILVER": ("KJPL_SILVERDEC_INR_1KG", "KJPL Silver Contract (1kg)", "SILVER", 1.0, "1kg"),
        "SILVERDEC": ("KJPL_SILVERDEC_INR_1KG", "KJPL Silver Contract (1kg)", "SILVER", 1.0, "1kg"),
    }

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line in ("R", "ping", "pong"):
            continue

        is_pipe = "|" in line and "\t" not in line
        fields = line.split("|") if is_pipe else line.split("\t")
        if len(fields) < 3:
            continue

        rec_type = fields[0].strip()

        if rec_type == "3":
            com_id = fields[1].strip()
            # Pipe WS: 3|com_id|buy|sell ; Tab kjpl.txt: 3\tcom_id\t-\tbuy\tsell\t...\tdate
            buy_raw = fields[2] if is_pipe else (fields[3] if len(fields) > 3 else "-")
            sell_raw = fields[3] if is_pipe else (fields[4] if len(fields) > 4 else "-")
            sell_val = _extract_number(sell_raw)
            buy_val = _extract_number(buy_raw)

            meta = LIVE_TYPE3_COM_ID_MAP.get(com_id)
            if not meta:
                continue

            if sell_val is None:
                continue

            comm_meta = rpanel_comms.get(com_id, {})
            diff_val = _extract_number(str(comm_meta.get("sell_diff", ""))) if comm_meta else None
            raw_name = str(comm_meta.get("com_name") or meta["product_name"])

            item = _build_validated_item(
                city_code=meta["city_code"],
                city_display_name=meta["city_display_name"],
                product_id=meta["product_id"],
                product_name=meta["product_name"],
                metal=meta["metal"],
                purity=meta["purity"],
                weight=meta["weight"],
                unit=meta["unit"],
                rate_type=meta["rate_type"],
                price=sell_val,
                currency="INR",
                buy_price=buy_val,
                source_product_id=com_id,
                raw_source_name=raw_name,
                diff_rate=diff_val,
                raw_payload_reference=line[:240],
            )
            if item.validation_status == "QUARANTINED":
                quarantined_items.append(item)
            else:
                valid_items.append(item)

        elif rec_type == "1":
            sym = fields[1].strip().upper()
            spec = type1_map.get(sym)
            if not spec:
                continue
            pid, pname, metal, unit, currency = spec
            if is_pipe:
                bid = _extract_number(fields[2] if len(fields) > 2 else None)
                ask = _extract_number(fields[3] if len(fields) > 3 else None)
                high = _extract_number(fields[4] if len(fields) > 4 else None)
                low = _extract_number(fields[5] if len(fields) > 5 else None)
            else:
                bid = _extract_number(fields[3] if len(fields) > 3 else None)
                ask = _extract_number(fields[4] if len(fields) > 4 else None)
                high = _extract_number(fields[5] if len(fields) > 5 else None)
                low = _extract_number(fields[6] if len(fields) > 6 else None)
            if ask is None and bid is None:
                continue
            item = _build_validated_item(
                city_code="ALL_INDIA",
                city_display_name="National",
                product_id=pid,
                product_name=pname,
                metal=metal,
                purity=0.999 if metal != "FX" else 1.0,
                weight=1.0,
                unit=unit,
                rate_type="KJPL_LIVE",
                price=ask if ask is not None else bid,
                buy_price=bid,
                high_price=high,
                low_price=low,
                currency=currency,
                source_product_id=sym,
                raw_source_name=sym,
                raw_payload_reference=line[:240],
            )
            if item.validation_status == "QUARANTINED":
                quarantined_items.append(item)
            else:
                valid_items.append(item)

        elif rec_type == "2":
            sym = fields[1].strip().upper()
            spec = type2_map.get(sym)
            if not spec:
                continue
            pid, pname, metal, wval, unit = spec
            bid = _extract_number(fields[2] if is_pipe and len(fields) > 2 else (fields[3] if len(fields) > 3 else None))
            ask = _extract_number(fields[3] if is_pipe and len(fields) > 3 else (fields[4] if len(fields) > 4 else None))
            high = _extract_number(fields[4] if is_pipe and len(fields) > 4 else (fields[5] if len(fields) > 5 else None))
            low = _extract_number(fields[5] if is_pipe and len(fields) > 5 else (fields[6] if len(fields) > 6 else None))
            if ask is None and bid is None:
                continue
            item = _build_validated_item(
                city_code="ALL_INDIA",
                city_display_name="National",
                product_id=pid,
                product_name=pname,
                metal=metal,
                purity=0.995 if metal == "GOLD" else 0.999,
                weight=wval,
                unit=unit,
                rate_type="KJPL_LIVE",
                price=ask if ask is not None else bid,
                buy_price=bid,
                high_price=high,
                low_price=low,
                currency="INR",
                source_product_id=sym,
                raw_source_name=sym,
                raw_payload_reference=line[:240],
            )
            if item.validation_status == "QUARANTINED":
                quarantined_items.append(item)
            else:
                valid_items.append(item)

        elif rec_type == "4":
            if is_pipe:
                rd = fields[2].strip() if len(fields) > 2 else "1"
                ms = fields[3].strip() if len(fields) > 3 else "0"
            else:
                rd = fields[3].strip() if len(fields) > 3 else "1"
                ms = fields[4].strip() if len(fields) > 4 else "0"
                ts_raw = fields[6].strip().strip('"') if len(fields) > 6 else ""
                if ts_raw:
                    source_updated_time = ts_raw
                    source_updated_at = parse_kjpl_type4_datetime(ts_raw)
            rate_display_enabled = (rd == "1")
            market_status = "CLOSED" if ms == "1" else "OPEN"

    # Fallback timestamp from rpaneldata if Type 4 didn't provide timestamp (e.g., WS frame)
    if source_updated_at is None and rpanel_json and isinstance(rpanel_json.get("rpaneldata"), dict):
        rp_ts = rpanel_json["rpaneldata"].get("lastupdatetime")
        if rp_ts:
            source_updated_time = str(rp_ts)
            rp_str = str(rp_ts)
            source_updated_at = (
                parse_kjpl_type4_datetime(rp_str)
                if "/" in rp_str
                else parse_full_kjpl_datetime(rp_str)
            )

    return ParsedKJPLPayload(
        observed_at=now,
        pipeline=source_label,
        source_updated_time=source_updated_time,
        source_updated_at=source_updated_at,
        source_timestamp_precision="FULL" if source_updated_at is not None else None,
        market_status=market_status,
        rate_display_enabled=rate_display_enabled,
        city_rates=valid_items,
        quarantined_rates=quarantined_items,
        raw_products_count=len(valid_items),
        extraction_errors=errors,
    )


def _extract_lbma_london_fixes(soup: BeautifulSoup) -> list[ParsedCityRate]:
    """
    Extract LBMA AM/PM fixes strictly as USD/oz LBMA_FIX records.
    Never mixes USD/oz values into domestic INR/g MJDTA products.
    """
    fixes: list[ParsedCityRate] = []
    seen_ids: set[str] = set()
    for table in soup.find_all("table", class_="chennairate_table"):
        txt_upper = table.get_text(" ", strip=True).upper()
        if "LBMA LONDON" not in txt_upper:
            continue
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            label = cells[0].upper()
            val = _extract_number(cells[1])
            if val is None:
                continue
            if "GOLD AM" in label and "LBMA_GOLD_AM_USD" not in seen_ids:
                seen_ids.add("LBMA_GOLD_AM_USD")
                fixes.append(_build_validated_item(
                    city_code="ALL_INDIA",
                    city_display_name="National",
                    product_id="LBMA_GOLD_AM_USD",
                    product_name="LBMA London Gold AM Fix",
                    metal="GOLD",
                    purity=0.995,
                    weight=1.0,
                    unit="oz",
                    rate_type="LBMA_FIX",
                    price=val,
                    currency="USD",
                    raw_source_name=cells[0],
                    raw_payload_reference=" | ".join(cells),
                ))
            elif "GOLD PM" in label and "LBMA_GOLD_PM_USD" not in seen_ids:
                seen_ids.add("LBMA_GOLD_PM_USD")
                fixes.append(_build_validated_item(
                    city_code="ALL_INDIA",
                    city_display_name="National",
                    product_id="LBMA_GOLD_PM_USD",
                    product_name="LBMA London Gold PM Fix",
                    metal="GOLD",
                    purity=0.995,
                    weight=1.0,
                    unit="oz",
                    rate_type="LBMA_FIX",
                    price=val,
                    currency="USD",
                    raw_source_name=cells[0],
                    raw_payload_reference=" | ".join(cells),
                ))
            elif "SILVER" in label and "LBMA_SILVER_USD" not in seen_ids:
                seen_ids.add("LBMA_SILVER_USD")
                fixes.append(_build_validated_item(
                    city_code="ALL_INDIA",
                    city_display_name="National",
                    product_id="LBMA_SILVER_USD",
                    product_name="LBMA London Silver Fix",
                    metal="SILVER",
                    purity=0.999,
                    weight=1.0,
                    unit="oz",
                    rate_type="LBMA_FIX",
                    price=val,
                    currency="USD",
                    raw_source_name=cells[0],
                    raw_payload_reference=" | ".join(cells),
                ))
    return fixes


def parse_kjpl_all_city_rates(html_content: str, reference_time: datetime | None = None) -> ParsedKJPLPayload:
    """
    Clean HTML parser for KJPL MJDTA reference rates, LBMA USD/oz benchmarks, and
    explicit structured commodity JSON/DOM tables.
    Strictly rejects ambiguous fallback table rows that caused ₹100 / ₹51 / USD-as-INR corruptions.
    """
    now = reference_time or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)

    soup = BeautifulSoup(html_content, "html.parser")
    errors: list[str] = []

    mjdta_tables = _extract_mjdta_tables(soup)
    gold_elem = soup.select_one(".gold-rate")
    silver_elem = soup.select_one(".silver-rate")
    time_elem = soup.select_one(".mjdma_data")

    mjdta_gold = _extract_number(gold_elem.get_text(strip=True)) if gold_elem else mjdta_tables.get("gold_no_gst")
    mjdta_silver = _extract_number(silver_elem.get_text(strip=True)) if silver_elem else mjdta_tables.get("silver_no_gst")
    source_clock_time = time_elem.get_text(" ", strip=True) if time_elem else (
        str(mjdta_tables["updated_full"]) if mjdta_tables.get("updated_full") else None
    )
    full_updated_text = str(mjdta_tables["updated_full"]) if mjdta_tables.get("updated_full") else None
    source_published_at = _parse_source_clock_time(
        source_clock_time,
        now,
        full_updated_text=full_updated_text,
    )
    if parse_full_kjpl_datetime(full_updated_text) or parse_full_kjpl_datetime(source_clock_time):
        source_timestamp_precision = "FULL"
    elif source_clock_time:
        clk_res = resolve_clock_only_kjpl_timestamp(source_clock_time, now)
        if clk_res.timestamp_ist is not None:
            source_timestamp_precision = "CLOCK_ONLY"
        elif clk_res.precision_status == "AMBIGUOUS_CLOCK_ONLY":
            source_timestamp_precision = "AMBIGUOUS_CLOCK_ONLY"
        else:
            source_timestamp_precision = None
    else:
        source_timestamp_precision = None

    g_gst_raw = mjdta_tables.get("gold_with_gst")
    s_gst_raw = mjdta_tables.get("silver_with_gst")
    mjdta_gold_with_gst = float(g_gst_raw) if isinstance(g_gst_raw, (int, float)) else None
    mjdta_silver_with_gst = float(s_gst_raw) if isinstance(s_gst_raw, (int, float)) else None

    city_rates_dict: dict[tuple[str, str], ParsedCityRate] = {}
    quarantined_list: list[ParsedCityRate] = []

    def _register(item: ParsedCityRate) -> None:
        if item.validation_status == "QUARANTINED":
            quarantined_list.append(item)
            return
        city_rates_dict[(item.city_code, item.product_id)] = item

    # 1. Explicit embedded JSON (<script id="commodity-data"> or explicit com_name JSON arrays)
    for script in soup.find_all("script"):
        content = script.string or ""
        if "com_name" in content and "sellrate" in content:
            json_matches = re.findall(r"\[\s*\{.*?\"com_name\".*?\}\s*\]", content, re.DOTALL)
            for jm in json_matches:
                try:
                    data = json.loads(jm)
                    for row in data:
                        com_id = str(row.get("com_id", "")).strip()
                        raw_name = str(row.get("com_name", "")).strip()
                        price = _extract_number(str(row.get("sellrate", "")))
                        diff_val = _extract_number(str(row.get("selldiff", "")))
                        if not price or not raw_name:
                            continue
                        resolved = _resolve_city_and_product(raw_name, com_id, price_hint=price)
                        _register(_build_validated_item(
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
                        ))
                except Exception as e:
                    errors.append(f"JSON script parse error: {e}")

    # 2. Explicit structured city table rows with data-com-id and td.rate (e.g., hydrated fixtures)
    for tr in soup.select("tr[data-com-id]"):
        com_id = str(tr.get("data-com-id", "")).strip()
        rate_cell = tr.select_one("td.rate")
        name_cell = tr.select_one("td.product-name") or tr.find("td")
        if not rate_cell or not name_cell:
            continue
        price = _extract_number(rate_cell.get_text(" ", strip=True))
        raw_name = name_cell.get_text(" ", strip=True)
        if not price or not raw_name:
            continue
        resolved = _resolve_city_and_product(raw_name, com_id, price_hint=price)
        if (resolved["city_code"], resolved["product_id"]) not in city_rates_dict:
            _register(_build_validated_item(
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
            ))

    # 3. MJDTA Gold & Silver Benchmarks (Chennai)
    if isinstance(mjdta_gold, (int, float)):
        _register(_build_validated_item(
            city_code="CHENNAI",
            city_display_name="Chennai",
            product_id="MJDTA_GOLD_24K",
            product_name="MJDTA Gold 24K Pure (Chennai Benchmark)",
            metal="GOLD",
            purity=0.999,
            weight=1.0,
            unit="1g",
            rate_type="MJDTA_BENCHMARK",
            price=float(mjdta_gold),
            currency="INR",
            source_product_id="MJDTA_GOLD",
            raw_source_name="MJDTA GOLD (Without GST)",
        ))
    if isinstance(mjdta_gold_with_gst, (int, float)):
        _register(_build_validated_item(
            city_code="CHENNAI",
            city_display_name="Chennai",
            product_id="MJDTA_GOLD_24K_GST",
            product_name="MJDTA Gold 24K (With 3% GST)",
            metal="GOLD",
            purity=0.999,
            weight=1.0,
            unit="1g",
            rate_type="MJDTA_BENCHMARK",
            price=float(mjdta_gold_with_gst),
            currency="INR",
            source_product_id="MJDTA_GOLD_GST",
            raw_source_name="MJDTA GOLD (With GST)",
        ))
    if isinstance(mjdta_silver, (int, float)):
        _register(_build_validated_item(
            city_code="CHENNAI",
            city_display_name="Chennai",
            product_id="MJDTA_SILVER",
            product_name="MJDTA Silver Benchmark (Chennai)",
            metal="SILVER",
            purity=0.999,
            weight=1.0,
            unit="1g",
            rate_type="MJDTA_BENCHMARK",
            price=float(mjdta_silver),
            currency="INR",
            source_product_id="2",
            raw_source_name="MJDTA SILVER (Without GST)",
        ))

    # 4. LBMA London Fixes (strictly USD/oz)
    for lbma_item in _extract_lbma_london_fixes(soup):
        _register(lbma_item)

    sorted_rates = sorted(city_rates_dict.values(), key=lambda r: (r.metal, r.city_code, r.product_id))

    return ParsedKJPLPayload(
        observed_at=now,
        pipeline="KJPL_MJDTA" if not any(r.rate_type in ("RETAIL", "WHOLESALE") for r in sorted_rates) else "KJPL_HTML",
        source_updated_time=source_clock_time,
        source_updated_at=source_published_at,
        source_timestamp_precision=source_timestamp_precision,
        mjdta_gold=float(mjdta_gold) if isinstance(mjdta_gold, (int, float)) else None,
        mjdta_silver=float(mjdta_silver) if isinstance(mjdta_silver, (int, float)) else None,
        mjdta_gold_with_gst=mjdta_gold_with_gst,
        mjdta_silver_with_gst=mjdta_silver_with_gst,
        city_rates=sorted_rates,
        quarantined_rates=quarantined_list,
        raw_products_count=len(sorted_rates),
        extraction_errors=errors,
    )
