#!/usr/bin/env python3
"""
DECOMMISSIONED: External Yahoo Finance market collector.

VMD Bullion enforces KJPL as the exclusive upstream source for Spot Gold ($),
Spot Silver ($), Spot INR (₹), and domestic city/MJDTA rates.
External yfinance scraping is permanently disabled.
"""
from __future__ import annotations

import sys


def collect() -> None:
    print(
        "[MARKET COLLECTOR DECOMMISSIONED] External Yahoo Finance scraping is disabled. "
        "International spot & FX feeds are ingested exclusively from KJPL via scripts/kjpl_live_worker.py."
    )


if __name__ == "__main__":
    collect()
    sys.exit(0)
