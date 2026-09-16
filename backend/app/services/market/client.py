import yfinance as yf


class MarketClient:
    def _get_latest_close(self, symbol: str) -> float:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d")

        if history.empty:
            raise RuntimeError(f"No market data returned for {symbol}")

        close = history["Close"].dropna()

        if close.empty:
            raise RuntimeError(f"Close price unavailable for {symbol}")

        return float(close.iloc[-1])

    def get_usdinr(self) -> float:
        return self._get_latest_close("USDINR=X")

    def get_gold_usd(self) -> float:
        return self._get_latest_close("GC=F")
    def get_silver_usd(self) -> float:
        return self._get_latest_close("SI=F")
