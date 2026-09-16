import yfinance as yf


class MarketClient:

    def get_usdinr(self) -> float:
        ticker = yf.Ticker("USDINR=X")

        history = ticker.history(period="1d")

        if history.empty:
            raise RuntimeError("No USD/INR market data returned")

        close = history["Close"].dropna()

        if close.empty:
            raise RuntimeError("USD/INR close price unavailable")

        return float(close.iloc[-1])
