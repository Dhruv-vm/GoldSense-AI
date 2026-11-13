from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
KJPL_HOME_URL = "http://www.kjpl.in/"
KJPL_TXT_URL = "http://www.kjpl.in/client/kjpl.txt"
KJPL_RPANEL_URL = "http://www.kjpl.in/index.php/C_booking/get_rpanel_data"

# Strict, explicit five-city non-persistent feeds mapping:
# Key: source_product_id -> (city_code, product_id)
NON_PERSISTENT_CITY_FEEDS: dict[str, tuple[str, str]] = {
    "48": ("CHENNAI", "GOLD_100G_999"),
    "49": ("BENGALURU", "GOLD_100G_999"),
    "50": ("MUMBAI", "GOLD_100G_999"),
    "51": ("COIMBATORE", "GOLD_100G_999"),
    "52": ("HYDERABAD", "GOLD_100G_999"),
}

NON_PERSISTENT_SOURCE_PRODUCT_IDS: frozenset[str] = frozenset(NON_PERSISTENT_CITY_FEEDS.keys())


def is_non_persistent_city_feed(
    source_product_id: str | None,
    city_code: str | None = None,
    product_id: str | None = None,
    source_name: str | None = None,
) -> bool:
    """
    Determines whether a rate observation belongs strictly to the five non-persistent KJPL city feeds.

    CRITICAL BOUNDARY SAFETY RULES:
    1. Returns True ONLY IF ALL THREE conditions match:
       - source_product_id is in {'48', '49', '50', '51', '52'}
       - city_code matches the expected mapped city (CHENNAI, BENGALURU, MUMBAI, COIMBATORE, HYDERABAD)
       - product_id matches the expected mapped product (GOLD_100G_999)
    2. If source_product_id, city_code, or product_id is missing (None, empty, or whitespace-only), returns False.
    3. Any record with an unknown, mismatched, or malformed identity returns False and follows safe persistent/quarantine handling.
    4. NEVER returns True for ID 47 (KJPL ALL_INDIA wholesale bar).
    5. NEVER returns True for MJDTA benchmarks (MJDTA_GOLD, MJDTA_GOLD_GST, 2).
    6. NEVER returns True for LBMA London fixes (LBMA_GOLD_AM, LBMA_GOLD_PM, LBMA_SILVER).
    7. NEVER returns True for KJPL Live contracts (GOLDDEC, SILVERDEC, SPOT-GOLD, SPOT-SILVER, SPOT-INR).
    8. NEVER uses broad rules like 'skip all KJPL' or 'skip anything with a city_code'.
    """
    if not source_product_id or not city_code or not product_id:
        return False

    spid = str(source_product_id).strip()
    if spid not in NON_PERSISTENT_SOURCE_PRODUCT_IDS:
        return False

    c_norm = str(city_code).strip().upper()
    p_norm = str(product_id).strip()

    expected_city, expected_prod = NON_PERSISTENT_CITY_FEEDS[spid]
    if c_norm != expected_city or p_norm != expected_prod:
        return False

    return True


def _format_pub_time_ist(pub_dt: datetime | None) -> str:
    if not pub_dt:
        return "Unverified"
    dt_ist = pub_dt.replace(tzinfo=timezone.utc).astimezone(IST) if pub_dt.tzinfo is None else pub_dt.astimezone(IST)
    return dt_ist.strftime("%d %b %I:%M %p IST")


def _recompute_freshness_dict(rate_dict: dict[str, Any]) -> dict[str, Any]:
    from app.services.data_service import get_freshness_details
    pub_iso = rate_dict.get("source_published_at")
    obs_iso = rate_dict.get("observed_at")
    ref_dt: datetime | None = None
    if pub_iso:
        try:
            ref_dt = datetime.fromisoformat(pub_iso)
        except Exception:
            pass
    if ref_dt is None and obs_iso:
        try:
            ref_dt = datetime.fromisoformat(obs_iso)
        except Exception:
            pass
    if ref_dt is not None:
        freshness = get_freshness_details(ref_dt, rate_type=rate_dict.get("rate_type", "RETAIL"))
        rate_copy = dict(rate_dict)
        rate_copy["freshness"] = freshness["status"]
        rate_copy["age_hours"] = freshness["age_hours"]
        rate_copy["age_seconds"] = freshness["age_seconds"]
        rate_copy["age_display"] = freshness["age_display"]
        return rate_copy
    return dict(rate_dict)


class CityLiveRateCache:
    """
    Thread-safe short-lived in-memory cache for the five KJPL city live-rate feeds (IDs 48-52).
    Enforces that invalid or missing city data NEVER overwrites a valid cached rate.
    Each city updates independently and cannot be substituted or copied to another.
    """

    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl_seconds = ttl_seconds
        self._rates: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last_source_fetch_ts: float = 0.0

    def update_rate(
        self,
        city_code: str,
        *,
        price: float,
        buy_price: float | None = None,
        source_product_id: str,
        product_id: str = "GOLD_100G_999",
        product_name: str | None = None,
        metal: str = "GOLD",
        purity: float = 0.999,
        weight: float = 1.0,
        product_weight_grams: float = 1.0,
        unit: str = "1g",
        rate_type: str = "RETAIL",
        currency: str = "INR",
        source_published_at: datetime | None = None,
        source_updated_time: str | None = None,
        observed_at: datetime | None = None,
        validation_status: str = "VALID",
        source_url: str = "http://www.kjpl.in/",
    ) -> tuple[bool, bool]:
        norm_city = city_code.strip().upper()
        if not is_non_persistent_city_feed(source_product_id, norm_city, product_id):
            return (False, False)

        # Requirement D.5: Missing or invalid city data does not overwrite a valid cached rate.
        if validation_status != "VALID":
            return (False, False)
        if price is None or price <= 0:
            return (False, False)
        if price < 5000.0 or price > 50000.0:
            return (False, False)

        now_utc = observed_at or datetime.now(timezone.utc)

        # Future timestamp rejection:
        if source_published_at is not None:
            pub_chk = source_published_at.replace(tzinfo=timezone.utc) if source_published_at.tzinfo is None else source_published_at
            if pub_chk > now_utc:
                return (False, False)

        pub_iso = source_published_at.isoformat() if source_published_at else None
        obs_iso = now_utc.isoformat()
        fresh_ref = source_published_at or now_utc

        from app.services.data_service import get_freshness_details
        freshness = get_freshness_details(fresh_ref, rate_type=rate_type)

        with self._lock:
            prev = self._rates.get(norm_city)
            prev_price = float(prev["latest_price"]) if prev and prev.get("latest_price") else None
            price_changed = (prev_price is None or abs(float(price) - prev_price) > 1e-4)
            diff_inr = round(float(price) - prev_price, 2) if prev_price is not None else 0.0
            pct = round((diff_inr / prev_price) * 100, 4) if (prev_price is not None and prev_price > 0) else 0.0

            city_display = {
                "CHENNAI": "Chennai",
                "BENGALURU": "Bengaluru",
                "MUMBAI": "Mumbai",
                "COIMBATORE": "Coimbatore",
                "HYDERABAD": "Hyderabad",
            }.get(norm_city, norm_city.title())

            prod_display_name = product_name or f"KJPL Gold 100 GMS 999 {city_display}"

            # Ensure source_updated_time matches IST formatted display
            formatted_src_time = (
                _format_pub_time_ist(source_published_at)
                if source_published_at
                else (source_updated_time or "Unverified")
            )

            # Requirement D.6 & D.7: Each city updates independently, no city rate copied or substituted.
            self._rates[norm_city] = {
                "city_code": norm_city,
                "city_display_name": city_display,
                "product_id": product_id,
                "product_name": prod_display_name,
                "metal": metal,
                "purity": purity,
                "weight": weight,
                "product_weight_grams": product_weight_grams,
                "unit": unit,
                "rate_type": rate_type,
                "latest_price": float(price),
                "buy_price": float(buy_price) if buy_price is not None else None,
                "previous_price": prev_price if prev_price is not None else float(price),
                "change_inr": diff_inr,
                "change_pct": pct,
                "per_gram_price": float(price),
                "normalized_price_per_gram": float(price),
                "currency": currency,
                "source_product_id": source_product_id,
                "validation_status": "VALID",
                "source_published_at": pub_iso,
                "source_updated_time": formatted_src_time,
                "observed_at": obs_iso,
                "last_verified_at": obs_iso,
                "freshness": freshness["status"],
                "age_hours": freshness["age_hours"],
                "age_seconds": freshness["age_seconds"],
                "age_display": freshness["age_display"],
                "source_url": source_url,
                "cached_at": time.time(),
            }
            return (True, price_changed)

    def get_rate(self, city_code: str) -> dict[str, Any] | None:
        with self._lock:
            rate = self._rates.get(city_code.strip().upper())
            return _recompute_freshness_dict(rate) if rate else None

    def get_all_rates(self) -> list[dict[str, Any]]:
        with self._lock:
            return [_recompute_freshness_dict(r) for r in self._rates.values()]

    def is_warm(self) -> bool:
        with self._lock:
            return len(self._rates) > 0

    def is_fresh(self) -> bool:
        with self._lock:
            if not self._rates:
                return False
            return (time.time() - self._last_source_fetch_ts) < self.ttl_seconds

    def mark_fetched(self) -> None:
        with self._lock:
            self._last_source_fetch_ts = time.time()

    def clear(self) -> None:
        with self._lock:
            self._rates.clear()
            self._last_source_fetch_ts = 0.0


# Global shared in-memory singleton cache
live_city_cache = CityLiveRateCache(ttl_seconds=30.0)


class CityLiveCollector:
    """
    Asynchronous background live collector owned by the FastAPI application process.
    Continuously polls the five KJPL city live feeds and updates live_city_cache in memory.

    Guarantees:
    - Single collection loop per API instance.
    - Decoupled from frontend requests: frontend refreshes never trigger source requests.
    - Collection cadence respects source frequency limits (poll_interval_sec, rpanel_refresh_sec).
    - Independent city updates: one city failure or update does not impact others.
    - Future or invalid timestamps NEVER overwrite valid cached rates.
    - Missing source data NEVER fabricates prices.
    - Stale cached rates are clearly marked.
    - Zero database connections or writes.
    - Clean, graceful shutdown via FastAPI lifespan.
    """

    def __init__(
        self,
        *,
        cache: CityLiveRateCache | None = None,
        poll_interval_sec: float | None = None,
        rpanel_refresh_sec: float | None = None,
        fetch_txt_fn: Callable[[], str] | None = None,
        fetch_rpanel_fn: Callable[[], dict[str, Any] | None] | None = None,
    ):
        self.cache = cache or live_city_cache
        self.poll_interval_sec = (
            poll_interval_sec
            if poll_interval_sec is not None
            else float(os.environ.get("KJPL_CITY_POLL_INTERVAL_SEC", "5.0"))
        )
        self.rpanel_refresh_sec = (
            rpanel_refresh_sec
            if rpanel_refresh_sec is not None
            else float(os.environ.get("KJPL_RPANEL_REFRESH_SEC", "300.0"))
        )
        self._fetch_txt_fn = fetch_txt_fn
        self._fetch_rpanel_fn = fetch_rpanel_fn
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._rpanel_cache: dict[str, Any] | None = None
        self._rpanel_fetched_at: float = 0.0
        self._poll_count: int = 0
        self._last_error: str | None = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _fetch_txt(self) -> str:
        if self._fetch_txt_fn is not None:
            return self._fetch_txt_fn()
        resp = requests.get(KJPL_TXT_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        return resp.text

    def _fetch_rpanel(self) -> dict[str, Any] | None:
        if self._fetch_rpanel_fn is not None:
            return self._fetch_rpanel_fn()
        try:
            resp = requests.get(KJPL_RPANEL_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    async def poll_once(self) -> int:
        loop = asyncio.get_running_loop()
        now_ts = time.time()

        # Refresh rpanel metadata if due
        if (
            self._rpanel_cache is None
            or (now_ts - self._rpanel_fetched_at) >= self.rpanel_refresh_sec
        ):
            try:
                rp = await loop.run_in_executor(None, self._fetch_rpanel)
                if rp:
                    self._rpanel_cache = rp
                    self._rpanel_fetched_at = now_ts
            except Exception:
                pass

        # Fetch kjpl.txt
        raw_text = await loop.run_in_executor(None, self._fetch_txt)
        if not raw_text or not raw_text.strip():
            return 0

        from app.services.kjpl.city_parser import parse_kjpl_live_feed

        now_utc = datetime.now(timezone.utc)
        payload = parse_kjpl_live_feed(
            raw_text,
            rpanel_json=self._rpanel_cache,
            reference_time=datetime.now(IST),
            source_label="FASTAPI_CITY_COLLECTOR",
        )

        updated_count = 0
        raw_src_time = (payload.source_updated_time or "")[:64] or None
        source_pub_utc = (
            payload.source_updated_at.astimezone(timezone.utc)
            if payload.source_updated_at is not None
            else None
        )

        # Reject future source timestamps
        if source_pub_utc is not None:
            chk_dt = (
                source_pub_utc.replace(tzinfo=timezone.utc)
                if source_pub_utc.tzinfo is None
                else source_pub_utc
            )
            if chk_dt > now_utc:
                return 0

        for r in payload.city_rates:
            if not is_non_persistent_city_feed(r.source_product_id, r.city_code, r.product_id):
                continue
            if r.price is None or r.price <= 0:
                continue

            ok, _ = self.cache.update_rate(
                r.city_code,
                price=float(r.price),
                buy_price=float(r.buy_price) if r.buy_price is not None else None,
                source_product_id=r.source_product_id,
                product_id=r.product_id,
                product_name=r.product_name,
                metal=r.metal,
                purity=float(r.purity),
                weight=float(r.weight),
                product_weight_grams=1.0,
                unit=r.unit,
                rate_type=r.rate_type,
                currency=r.currency,
                source_published_at=source_pub_utc,
                source_updated_time=raw_src_time,
                observed_at=now_utc,
                validation_status="VALID",
                source_url=KJPL_TXT_URL,
            )
            if ok:
                updated_count += 1

        self.cache.mark_fetched()
        self._poll_count += 1
        return updated_count

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except Exception as e:
                self._last_error = str(e)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_sec,
                )
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self, timeout: float = 5.0) -> None:
        if not self.is_running() and self._task is None:
            return
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
            self._task = None


_collector_instance: CityLiveCollector | None = None
_collector_lock = threading.Lock()


def get_city_live_collector() -> CityLiveCollector:
    global _collector_instance
    with _collector_lock:
        if _collector_instance is None:
            _collector_instance = CityLiveCollector()
        return _collector_instance


def set_city_live_collector(collector: CityLiveCollector | None) -> None:
    global _collector_instance
    with _collector_lock:
        _collector_instance = collector
