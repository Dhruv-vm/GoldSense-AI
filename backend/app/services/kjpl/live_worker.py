from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import websockets

from app.db.session import SessionLocal
from app.models.bullion import CollectorRun, DataSourceStatus
from app.services.kjpl.city_parser import parse_kjpl_live_feed
from app.services.kjpl.persistence import persist_parsed_payload

IST = ZoneInfo("Asia/Kolkata")
KJPL_HOME_URL = "http://www.kjpl.in/"
KJPL_TXT_URL = "http://www.kjpl.in/client/kjpl.txt"
KJPL_RPANEL_URL = "http://www.kjpl.in/index.php/C_booking/get_rpanel_data"
KJPL_WS_URL = "ws://www.kjpl.in/ws"
LOCK_FILE_PATH = Path(os.environ.get("KJPL_WORKER_LOCK_PATH", "/tmp/vmd_kjpl_live_worker.lock"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


class KJPLLiveWorker:
    """
    Single-writer continuous KJPL Pipeline B worker intended for Oracle Cloud Always Free VM.
    Connects to ws://www.kjpl.in/ws (with Socket token discovery) and falls back cleanly
    to controlled http://www.kjpl.in/client/kjpl.txt polling when WS is unavailable.
    Never fabricates ticks or persists unchanged duplicate observations.
    """

    def __init__(
        self,
        *,
        verify_interval_seconds: float = 60.0,
        rpanel_refresh_seconds: float = 300.0,
        poll_fallback_seconds: float = 5.0,
    ):
        self.verify_interval_seconds = verify_interval_seconds
        self.rpanel_refresh_seconds = rpanel_refresh_seconds
        self.poll_fallback_seconds = poll_fallback_seconds
        self._stop_event = asyncio.Event()
        self._lock_fh = None
        self._last_persist_ts = 0.0
        self._last_prices: dict[tuple[str, str], float] = {}
        self._rpanel_cache: dict[str, Any] | None = None
        self._rpanel_fetched_at = 0.0
        self._ws_cache: dict[str, str] = {}

    def acquire_single_writer_lock(self) -> None:
        LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fh = LOCK_FILE_PATH.open("w")
        try:
            fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fh.write(f"pid={os.getpid()} started={datetime.now(timezone.utc).isoformat()}\n")
            self._lock_fh.flush()
        except OSError as exc:
            raise RuntimeError(f"Another KJPLLiveWorker instance already holds {LOCK_FILE_PATH}") from exc

    def release_lock(self) -> None:
        if self._lock_fh:
            try:
                fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
                self._lock_fh.close()
            except Exception:
                pass
            self._lock_fh = None

    def request_shutdown(self) -> None:
        self._stop_event.set()

    def fetch_socket_token(self) -> str | None:
        try:
            resp = requests.get(KJPL_HOME_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            m = re.search(r'SOCKET_TOKEN\s*=\s*["\']([0-9a-fA-F]+)["\']', resp.text)
            if m:
                return m.group(1)
        except Exception as exc:
            print(f"[KJPL LIVE WORKER] Token discovery note: {exc}")
        return None

    def refresh_rpanel_if_due(self, force: bool = False) -> dict[str, Any] | None:
        now = time.time()
        if not force and self._rpanel_cache is not None and (now - self._rpanel_fetched_at) < self.rpanel_refresh_seconds:
            return self._rpanel_cache
        try:
            resp = requests.get(KJPL_RPANEL_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            self._rpanel_cache = resp.json()
            self._rpanel_fetched_at = now
        except Exception as exc:
            print(f"[KJPL LIVE WORKER] get_rpanel_data note: {exc}")
        return self._rpanel_cache

    def _merge_ws_frame(self, raw_msg: str) -> str:
        """Mirror booking.js processWsData() field-level merge for partial pipe/tab updates."""
        text = raw_msg.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "rate" in parsed:
                text = str(parsed["rate"])
            elif isinstance(parsed, str):
                text = parsed
        except Exception:
            pass

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line in ("R", "ping", "pong"):
                continue
            sep = "|" if ("|" in line and "\t" not in line) else "\t"
            fields = line.split(sep)
            if len(fields) < 2:
                continue
            key = f"{fields[0]}_{fields[1]}"
            if key in self._ws_cache:
                prev = self._ws_cache[key].split(sep)
                merged = [
                    (fields[i] if i < len(fields) and fields[i] != "" else (prev[i] if i < len(prev) else ""))
                    for i in range(max(len(prev), len(fields)))
                ]
                self._ws_cache[key] = sep.join(merged)
            else:
                self._ws_cache[key] = line
        return "\n".join(self._ws_cache.values())

    def _process_payload_text(self, raw_text: str, source_label: str) -> None:
        rp = self.refresh_rpanel_if_due()
        payload = parse_kjpl_live_feed(
            raw_text,
            rpanel_json=rp,
            reference_time=datetime.now(IST),
            source_label=source_label,
        )
        if not payload.city_rates and not payload.quarantined_rates:
            return

        current_prices = {(r.city_code, r.product_id): r.price for r in payload.city_rates}
        has_price_delta = any(
            abs(self._last_prices.get(k, -1.0) - v) > 1e-4
            for k, v in current_prices.items()
        )
        now = time.time()
        verify_due = (now - self._last_persist_ts) >= self.verify_interval_seconds

        if not has_price_delta and not verify_due and not payload.quarantined_rates:
            return

        run_id = uuid.uuid4().hex[:12]
        t0 = time.time()
        res = persist_parsed_payload(
            payload,
            source_url=KJPL_WS_URL if source_label == "KJPL_LIVE_WS" else KJPL_TXT_URL,
            source_key="KJPL_LIVE",
            mirror_csv=False,
        )
        self._last_prices.update(current_prices)
        self._last_persist_ts = now

        if has_price_delta or payload.quarantined_rates:
            duration = round(time.time() - t0, 3)
            with SessionLocal() as s:
                s.add(CollectorRun(
                    collector_name="KJPL_LIVE_WORKER",
                    run_id=run_id,
                    status="SUCCESS",
                    records_extracted=res.get("records_extracted", 0),
                    records_inserted=res.get("records_inserted", 0),
                    records_changed=res.get("records_changed", 0),
                    records_quarantined=res.get("records_quarantined", 0),
                    duration_seconds=duration,
                    executed_at=datetime.now(timezone.utc),
                ))
                s.commit()

    def _record_source_outage(self, err: str) -> None:
        now_utc = datetime.now(timezone.utc)
        try:
            with SessionLocal() as s:
                ds = s.execute(select_ds_stmt("KJPL_LIVE")).scalar_one_or_none()
                if ds:
                    ds.last_failed_run = now_utc
                    ds.current_status = "DOWN"
                    ds.error_message = err[:500]
                    ds.updated_at = now_utc
                s.add(CollectorRun(
                    collector_name="KJPL_LIVE_WORKER",
                    run_id=uuid.uuid4().hex[:12],
                    status="SOURCE_UNAVAILABLE",
                    records_extracted=0,
                    records_inserted=0,
                    records_changed=0,
                    records_quarantined=0,
                    duration_seconds=0.0,
                    error_message=err[:500],
                    executed_at=now_utc,
                ))
                s.commit()
        except Exception as db_exc:
            print(f"[KJPL LIVE WORKER] Failed to record outage telemetry: {db_exc}")

    async def _poll_kjpl_txt_once(self) -> bool:
        try:
            resp = requests.get(KJPL_TXT_URL, headers={"User-Agent": USER_AGENT}, timeout=12)
            resp.raise_for_status()
            self._process_payload_text(resp.text, "KJPL_LIVE_TXT")
            return True
        except Exception as exc:
            self._record_source_outage(f"kjpl.txt poll error: {exc}")
            return False

    async def run_forever(self) -> None:
        self.acquire_single_writer_lock()
        backoff = 2.0
        try:
            while not self._stop_event.is_set():
                token = self.fetch_socket_token()
                if not token:
                    ok = await self._poll_kjpl_txt_once()
                    await asyncio.sleep(self.poll_fallback_seconds if ok else min(backoff, 60.0))
                    backoff = 2.0 if ok else min(backoff * 2, 60.0)
                    continue

                try:
                    async with websockets.connect(
                        KJPL_WS_URL,
                        subprotocols=[token],
                        open_timeout=10,
                        ping_interval=25,
                        ping_timeout=10,
                    ) as ws:
                        print("[KJPL LIVE WORKER] WebSocket connected to ws://www.kjpl.in/ws")
                        backoff = 2.0
                        self.refresh_rpanel_if_due(force=True)
                        # Initial snapshot via kjpl.txt guarantees full state + Date/Time string immediately
                        await self._poll_kjpl_txt_once()

                        while not self._stop_event.is_set():
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            except asyncio.TimeoutError:
                                continue
                            raw_str = msg if isinstance(msg, str) else msg.decode("utf-8", errors="replace")
                            if raw_str in ("R", "ping", "pong"):
                                continue
                            merged = self._merge_ws_frame(raw_str)
                            self._process_payload_text(merged, "KJPL_LIVE_WS")
                except Exception as ws_exc:
                    print(f"[KJPL LIVE WORKER] WS disconnected ({ws_exc}); falling back to kjpl.txt & retrying in {backoff}s")
                    await self._poll_kjpl_txt_once()
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(backoff * 2, 60.0)
        finally:
            self.release_lock()


def select_ds_stmt(source_name: str):
    from sqlalchemy import select
    return select(DataSourceStatus).where(DataSourceStatus.source_name == source_name)
