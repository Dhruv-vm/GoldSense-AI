#!/usr/bin/env python3
"""
VMD Bullion — Continuous KJPL Live Worker CLI (Pipeline B)

Run under systemd on Oracle Cloud Always Free VM:
  PYTHONPATH=backend python scripts/kjpl_live_worker.py
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

os.environ.setdefault("DB_USE_NULLPOOL", "false")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.kjpl.live_worker import KJPLLiveWorker


def main() -> None:
    worker = KJPLLiveWorker(
        verify_interval_seconds=float(os.environ.get("KJPL_VERIFY_INTERVAL_SEC", "60")),
        rpanel_refresh_seconds=float(os.environ.get("KJPL_RPANEL_REFRESH_SEC", "300")),
        poll_fallback_seconds=float(os.environ.get("KJPL_POLL_FALLBACK_SEC", "5")),
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(signum, _frame):
        print(f"[KJPL LIVE WORKER] Received signal {signum}; shutting down gracefully...")
        worker.request_shutdown()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        loop.run_until_complete(worker.run_forever())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
