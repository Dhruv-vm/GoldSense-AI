from __future__ import annotations

from app.services.data_service import get_market_trading_status


def test_market_trading_status_fields():
    status = get_market_trading_status()
    assert isinstance(status, dict)
    assert "indian_physical_market" in status
    assert "global_futures_market" in status
    assert "server_time_ist" in status
    assert status["indian_physical_market"] in ("OPEN", "SUNDAY_CLOSED", "AFTER_HOURS")
    assert status["global_futures_market"] in ("OPEN", "WEEKEND_CLOSED", "DAILY_SETTLEMENT_BREAK")
