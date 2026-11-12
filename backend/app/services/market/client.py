from __future__ import annotations


class MarketClient:
    """
    Deprecated external Yahoo Finance market client.
    Disabled per VMD Bullion exclusive-KJPL data-source policy: international Spot Gold,
    Spot Silver, and Spot INR must originate exclusively from KJPL Type 1 feeds.
    """

    def _disabled(self, symbol: str) -> float:
        raise RuntimeError(
            f"External Yahoo Finance provider disabled for '{symbol}'. "
            "Use KJPL Live Terminal Type 1 feeds (KJPL_SPOT_GOLD_USD, KJPL_SPOT_SILVER_USD, KJPL_SPOT_USDINR)."
        )

    def get_usdinr(self) -> float:
        return self._disabled("USDINR")

    def get_gold_usd(self) -> float:
        return self._disabled("XAUUSD")

    def get_silver_usd(self) -> float:
        return self._disabled("XAGUSD")
